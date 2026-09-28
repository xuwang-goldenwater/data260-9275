"""
HW4 Part 4 - grounded RAG question answering and a context-engineering study.

    make run-rag4            # all runs (needs Ollama running with qwen3:8b)
    make rag4-summary        # evaluation table, after filling rag_eval.csv

Pipeline
  corpus   reports/hw03/corpus/*.txt (89 FDA recall notices + 21 CFR Part 7)
  chunk    llama-index SentenceSplitter, chunk_size=500, chunk_overlap=50 (tokens)
           each chunk keeps text, source (file name) and chunk_id
  embed    sentence-transformers/all-MiniLM-L6-v2, vectors L2-normalised
  store    FAISS IndexFlatIP -> inner product of unit vectors = cosine score
  answer   src/model_client.py (Ollama, qwen3:8b, temperature 0, thinking off)

Configurations (same six questions)
  A  No RAG         question only
  B  Basic RAG      top-k raw chunks pasted in, no labels, no rules
  C  Context RAG    wider candidate pool (2k) -> drop chunks below the score
                    threshold -> drop duplicates (same text, or embedding
                    cosine >= DEDUP_COSINE to a chunk already kept) -> keep
                    the best k -> order by score, label [S1].. with source
                    and chunk_id -> trim to a token budget -> grounding rules.
                    If nothing survives the threshold, the refusal sentence
                    is returned without calling the model (the "guard").

Every retrieval is printed with source and score BEFORE the model is called,
so a retrieval failure is visible separately from a generation failure.

Output (reports/hw04/raw/)
  rag_retrievals.txt / .jsonl   printed top-k retrievals (every run)
  rag_answers.jsonl             every model call: prompt, answer, tokens, latency
  rag_comparison.md             A / B / C side by side for Q1-Q6
  rag_ksweep.md / .json         k = 1, 3, 5 for Q2 and Q3 (B and C)
  rag_eval.csv                  evaluation sheet: automatic columns + two
                                columns for you to fill (correct_answer, grounded)
  rag_eval_table.md             summary table (written by --summary)
  rag_run_meta.json             models, parameters, timestamps
"""
import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

CORPUS_DIR = ROOT / "reports" / "hw03" / "corpus"
QUESTIONS_FILE = ROOT / "reports" / "hw04" / "rag_questions.yaml"
RAW_DIR = ROOT / "reports" / "hw04" / "raw"

SEED = 9275
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL = "qwen3:8b"

CHUNK_SIZE = 500            # tokens
CHUNK_OVERLAP = 50          # tokens
TOP_K = 3
SWEEP_KS = [1, 3, 5]
SWEEP_QUESTIONS = ["Q2", "Q3"]

# Context engineering (config C). Chosen before the graded run; see report.
SCORE_THRESHOLD = 0.35      # cosine below this = irrelevant, dropped
DEDUP_COSINE = 0.92         # two chunks this similar say the same thing
CANDIDATE_MULTIPLIER = 2    # C looks at 2k candidates to still have k after dropping
CONTEXT_TOKEN_BUDGET = 1600 # total tokens of source text allowed in the prompt

REFUSAL = "I cannot answer this question from the provided documents."

SYSTEM_PLAIN = "You are a helpful assistant. Answer the question concisely."

SYSTEM_GROUNDED = f"""You answer questions about food recall notices using ONLY the numbered sources provided.
Rules:
1. Use only facts stated in the sources. Do not use outside knowledge.
2. After every sentence, cite the source number(s) it came from in square brackets, e.g. [S1] or [S1][S3].
3. If the sources do not contain enough evidence to answer, reply with exactly this sentence and nothing else:
{REFUSAL}
4. If the question could refer to several different recalls, say that briefly, then give only what the sources support, with citations.
5. Keep the answer under 120 words."""


# ---- corpus, chunks, index ---------------------------------------------------

def load_chunks():
    """Split every corpus file into chunks: {chunk_id, source, text, tokens}."""
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.utils import get_tokenizer

    tokenizer = get_tokenizer()
    splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        for i, piece in enumerate(splitter.split_text(text)):
            chunks.append({
                "chunk_id": f"{path.stem}#{i}",
                "source": path.name,
                "text": piece,
                "tokens": len(tokenizer(piece)),
                "sha": hashlib.sha256(piece.encode("utf-8")).hexdigest()[:16],
            })
    return chunks, tokenizer


class Embedder:
    """MiniLM through sentence-transformers; returns unit-length float32 vectors.

    device="cpu" on purpose. The first graded run on the Mac let
    sentence-transformers pick Apple's MPS backend, and the same question then
    got different embeddings (and a different top-k) on different calls - for
    example Q4 scored 0.65 in config B and 0.11 in config C. CPU encoding of a
    model this small is fast and repeatable. VectorStore.self_check() below
    fails the run if that ever happens again.
    """

    def __init__(self, name=EMBED_MODEL_NAME, device="cpu"):
        from sentence_transformers import SentenceTransformer
        self.name = name
        self.device = device
        self.model = SentenceTransformer(name, device=device)

    def encode(self, texts):
        vecs = self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                 show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")


class VectorStore:
    """FAISS flat inner-product index over normalised vectors (= cosine)."""

    def __init__(self, chunks, embedder):
        import faiss
        faiss.omp_set_num_threads(1)          # avoid clashing with torch's OpenMP on macOS
        self.chunks = chunks
        self.embedder = embedder
        self.vectors = embedder.encode([c["text"] for c in chunks])
        self.index = faiss.IndexFlatIP(self.vectors.shape[1])
        self.index.add(self.vectors)
        self._query_cache = {}

    def query_vector(self, question):
        """Each question is embedded once, so configs B, C and every k see the same vector."""
        if question not in self._query_cache:
            self._query_cache[question] = self.embedder.encode([question])
        return self._query_cache[question]

    def search(self, question, k):
        q = self.query_vector(question)
        scores, ids = self.index.search(q, k)
        # FAISS must agree with a plain numpy dot product over all chunks.
        brute = np.argsort(-(self.vectors @ q[0]))[:k]
        if list(ids[0]) != list(brute) and not np.allclose(
                np.sort(self.vectors[ids[0]] @ q[0]), np.sort(self.vectors[brute] @ q[0]), atol=1e-5):
            raise RuntimeError(f"FAISS and numpy disagree for {question!r}: {ids[0]} vs {brute}")
        return [{**self.chunks[i], "row": int(i), "score": round(float(s), 4)}
                for s, i in zip(scores[0], ids[0]) if i >= 0]

    def cosine(self, row_a, row_b):
        return float(self.vectors[row_a] @ self.vectors[row_b])

    def self_check(self, questions):
        """Stop before any model call if embeddings are not repeatable."""
        sample = [c["text"] for c in self.chunks[:8]]
        again = self.embedder.encode(sample)
        chunk_drift = float(np.max(np.abs(again - self.vectors[:8])))
        q1 = self.embedder.encode(questions)
        q2 = self.embedder.encode(questions)
        query_drift = float(np.max(np.abs(q1 - q2)))
        report = {"device": self.embedder.device, "chunk_reencode_max_abs_diff": chunk_drift,
                  "query_reencode_max_abs_diff": query_drift}
        print(f"embedding self-check: {report}")
        if chunk_drift > 1e-4 or query_drift > 1e-4:
            raise RuntimeError(f"embeddings are not repeatable: {report}")
        return report


# ---- context building ---------------------------------------------------------

def basic_context(store, question, k):
    """Config B: the raw top-k, in score order, nothing removed."""
    hits = store.search(question, k)
    for h in hits:
        h["decision"] = "kept"
    return hits, hits


def engineered_context(store, question, k, tokenizer):
    """Config C: filter, de-duplicate, keep k, trim to the token budget.

    Returns (all candidates with a decision each, the kept chunks in order).
    """
    candidates = store.search(question, k * CANDIDATE_MULTIPLIER)
    kept, used_tokens = [], 0
    for c in candidates:
        if c["score"] < SCORE_THRESHOLD:
            c["decision"] = f"dropped: score < {SCORE_THRESHOLD}"
        elif any(c["sha"] == x["sha"] for x in kept):
            c["decision"] = "dropped: exact duplicate text"
        elif any(store.cosine(c["row"], x["row"]) >= DEDUP_COSINE for x in kept):
            twin = max(kept, key=lambda x: store.cosine(c["row"], x["row"]))
            c["decision"] = f"dropped: near-duplicate of {twin['chunk_id']}"
        elif len(kept) >= k:
            c["decision"] = "dropped: beyond k"
        elif used_tokens + c["tokens"] > CONTEXT_TOKEN_BUDGET:
            c["decision"] = f"dropped: token budget {CONTEXT_TOKEN_BUDGET}"
        else:
            c["decision"] = "kept"
            kept.append(c)
            used_tokens += c["tokens"]
    return candidates, kept      # candidates are already in score order


def build_messages(config, question, kept):
    if config == "A":
        return [{"role": "system", "content": SYSTEM_PLAIN},
                {"role": "user", "content": question}]
    if config == "B":
        context = "\n\n".join(c["text"] for c in kept)
        return [{"role": "system", "content": SYSTEM_PLAIN},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"}]
    blocks = [f"[S{i}] (source: {c['source']}, chunk: {c['chunk_id']}, score: {c['score']:.2f})\n{c['text']}"
              for i, c in enumerate(kept, start=1)]
    return [{"role": "system", "content": SYSTEM_GROUNDED},
            {"role": "user", "content": "Sources:\n\n" + "\n\n".join(blocks) +
             f"\n\nQuestion: {question}\nAnswer:"}]


# ---- answer checks --------------------------------------------------------------

REFUSAL_PATTERNS = [
    r"cannot answer this question from the provided documents",
    r"\b(can ?not|can't|unable to) (answer|determine|find)",
    r"\b(do not|don't|does not) (have|contain|mention|provide|include)",
    r"\bnot (mentioned|provided|included|stated|specified|available) in",
    r"\bno (information|mention|evidence)",
]


def clean_answer(text):
    """qwen3 may still emit a <think> block; it is not part of the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def is_refusal(answer):
    a = answer.lower()
    return any(re.search(p, a) for p in REFUSAL_PATTERNS)


def is_exact_refusal(answer):
    return answer.strip().rstrip(".").lower() == REFUSAL.rstrip(".").lower()


def cited_sources(answer):
    return sorted({int(n) for n in re.findall(r"\[S(\d+)\]", answer)})


def format_ok(answer, n_sources):
    """C's format rule: the exact refusal, or at least one valid [S#] and no invalid one."""
    if is_exact_refusal(answer):
        return True
    cites = cited_sources(answer)
    return bool(cites) and all(1 <= n <= n_sources for n in cites)


def retrieval_ok(question, kept):
    """Every evidence fragment appears in some chunk that went into the prompt."""
    if not question["evidence"]:
        return None
    text = " ".join(c["text"].lower() for c in kept)
    return all(e.lower() in text for e in question["evidence"])


def auto_correct(question, answer):
    if question["must_refuse"]:
        return is_refusal(answer)
    if is_refusal(answer) and not question["answer_keywords"]:
        return False
    a = answer.lower()
    return all(k.lower() in a for k in question["answer_keywords"])


# ---- running ----------------------------------------------------------------------

class Recorder:
    """Prints and stores every retrieval and every answer."""

    # Written to *.partial first and renamed only when the whole run finishes,
    # so stopping a run halfway (Ctrl+C) never wipes the results of the last
    # complete run.
    NAMES = ["rag_retrievals.txt", "rag_retrievals.jsonl", "rag_answers.jsonl"]

    def __init__(self):
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self.retr_txt, self.retr_jsonl, self.answers = (
            open(RAW_DIR / (name + ".partial"), "w", encoding="utf-8") for name in self.NAMES)

    def retrieval(self, run_id, question, config, k, candidates):
        lines = [f"--- {run_id} | {question['id']} | config {config} | k={k} ---",
                 f"Q: {question['question']}"]
        for rank, c in enumerate(candidates, start=1):
            preview = " ".join(c["text"].split())[:110]
            lines.append(f"  #{rank} score={c['score']:.4f}  {c['chunk_id']}  [{c['decision']}]")
            lines.append(f"       {preview}...")
        block = "\n".join(lines)
        print(block, flush=True)
        self.retr_txt.write(block + "\n\n")
        self.retr_jsonl.write(json.dumps({
            "run_id": run_id, "question_id": question["id"], "config": config, "k": k,
            "candidates": [{"rank": r, "chunk_id": c["chunk_id"], "source": c["source"],
                            "score": c["score"], "tokens": c["tokens"], "sha": c["sha"],
                            "decision": c["decision"]}
                           for r, c in enumerate(candidates, start=1)],
        }) + "\n")

    def answer(self, record):
        print(f"  => [{record['config']} k={record['k']}] {record['answer'][:300]}\n", flush=True)
        self.answers.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self):
        for f in (self.retr_txt, self.retr_jsonl, self.answers):
            f.close()
        for name in self.NAMES:
            (RAW_DIR / (name + ".partial")).replace(RAW_DIR / name)


def run_one(run_id, question, config, k, store, tokenizer, llm, rec):
    """Retrieve (print first), then call the model. Returns the answer record."""
    kept, candidates = [], []
    if config == "B":
        candidates, kept = basic_context(store, question["question"], k)
    elif config == "C":
        candidates, kept = engineered_context(store, question["question"], k, tokenizer)
    if config == "A":
        print(f"--- {run_id} | {question['id']} | config A (no retrieval) ---\nQ: {question['question']}")
    else:
        rec.retrieval(run_id, question, config, k, candidates)

    messages = build_messages(config, question["question"], kept)
    if config == "C" and not kept:
        answer, llm_called, usage = REFUSAL, False, {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0}
    else:
        resp = llm.complete(messages)
        answer, llm_called = clean_answer(resp.text), True
        usage = {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                 "latency_ms": round(resp.latency_ms, 1)}

    record = {
        "run_id": run_id, "question_id": question["id"], "type": question["type"],
        "config": config, "k": k if config != "A" else None,
        "question": question["question"], "answer": answer, "llm_called": llm_called,
        "kept_chunks": [c["chunk_id"] for c in kept],
        "kept_scores": [c["score"] for c in kept],
        "context_tokens": sum(c["tokens"] for c in kept),
        "retrieval_ok": retrieval_ok(question, kept) if config != "A" else None,
        "refused": is_refusal(answer),
        "format_ok": format_ok(answer, len(kept)) if config == "C" else None,
        "cited": cited_sources(answer),
        "auto_correct": auto_correct(question, answer),
        "messages": messages,
        **usage,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    rec.answer(record)
    return record


def run_all(questions, store, tokenizer, llm, embed_name, llm_name, self_check=None):
    rec = Recorder()
    started = datetime.now().isoformat(timespec="seconds")
    print(f"===== run-rag4 {started}  chunks={len(store.chunks)}  embed={embed_name}  llm={llm_name} =====")
    main_runs, sweep_runs, n = [], [], 0

    for q in questions:
        for config in ["A", "B", "C"]:
            n += 1
            main_runs.append(run_one(f"main-{n:02d}", q, config, TOP_K, store, tokenizer, llm, rec))

    for qid in SWEEP_QUESTIONS:
        q = next(x for x in questions if x["id"] == qid)
        for config in ["B", "C"]:
            for k in SWEEP_KS:
                n += 1
                sweep_runs.append(run_one(f"sweep-{n:02d}", q, config, k, store, tokenizer, llm, rec))
    rec.close()

    write_comparison(questions, main_runs)
    write_sweep(sweep_runs)
    write_eval_sheet(main_runs)
    meta = {
        "started_at": started, "finished_at": datetime.now().isoformat(timespec="seconds"),
        "corpus_dir": str(CORPUS_DIR.relative_to(ROOT)),
        "documents": len({c["source"] for c in store.chunks}), "chunks": len(store.chunks),
        "chunk_size_tokens": CHUNK_SIZE, "chunk_overlap_tokens": CHUNK_OVERLAP,
        "embed_model": embed_name, "vector_store": "FAISS IndexFlatIP (cosine on unit vectors)",
        "llm": llm_name, "temperature": 0.0, "top_k": TOP_K, "sweep_ks": SWEEP_KS,
        "sweep_questions": SWEEP_QUESTIONS, "score_threshold": SCORE_THRESHOLD,
        "dedup_cosine": DEDUP_COSINE, "candidate_multiplier": CANDIDATE_MULTIPLIER,
        "context_token_budget": CONTEXT_TOKEN_BUDGET, "seed": SEED,
        "questions_sha256": hashlib.sha256(QUESTIONS_FILE.read_bytes()).hexdigest(),
        "model_calls": sum(r["llm_called"] for r in main_runs + sweep_runs),
        "embedding_self_check": self_check,
        "versions": package_versions(),
    }
    (RAW_DIR / "rag_run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


def package_versions():
    from importlib.metadata import PackageNotFoundError, version
    out = {"python": sys.version.split()[0]}
    for pkg in ["torch", "sentence-transformers", "faiss-cpu", "llama-index-core", "numpy", "ollama"]:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = None
    return out


# ---- reports ---------------------------------------------------------------------

def short(text, n=220):
    t = " ".join(text.split()).replace("|", "\\|")
    return t if len(t) <= n else t[:n] + "…"


def write_comparison(questions, runs):
    lines = ["# No-RAG vs Basic RAG vs Context-engineered RAG (k = 3)", ""]
    for q in questions:
        lines += [f"## {q['id']} ({q['type']})", "", f"**Q:** {q['question']}", "",
                  f"**Expected:** {short(q['expected_answer'], 400)}", "",
                  "| Config | Chunks in prompt (score) | Retrieval ok | Refused | Answer |",
                  "|---|---|---|---|---|"]
        for r in [x for x in runs if x["question_id"] == q["id"]]:
            chunks = ", ".join(f"{c} ({s:.2f})" for c, s in zip(r["kept_chunks"], r["kept_scores"])) or "—"
            lines.append(f"| {r['config']} | {chunks} | {r['retrieval_ok']} | {r['refused']} | {short(r['answer'])} |")
        lines.append("")
    (RAW_DIR / "rag_comparison.md").write_text("\n".join(lines), encoding="utf-8")


def write_sweep(runs):
    rows = []
    for r in runs:
        rows.append({k: r[k] for k in ["question_id", "config", "k", "kept_chunks", "kept_scores",
                                       "context_tokens", "retrieval_ok", "refused", "auto_correct",
                                       "input_tokens", "latency_ms", "answer"]})
    (RAW_DIR / "rag_ksweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    retr = {}
    with open(RAW_DIR / "rag_retrievals.jsonl", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            retr[(x["question_id"], x["config"], x["k"])] = x   # sweep rows overwrite main k=3 (same content)

    lines = ["# top_k sweep (k = 1, 3, 5)", "",
             "| Q | Config | k | Chunks in prompt (score) | Dropped by C | Context tokens | Retrieval ok | Auto-correct | Answer |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cands = retr.get((r["question_id"], r["config"], r["k"]), {}).get("candidates", [])
        dropped = "; ".join(f"{c['chunk_id']}: {c['decision'][9:]}" for c in cands
                            if c["decision"] != "kept") if r["config"] == "C" else "—"
        chunks = ", ".join(f"{c} ({s:.2f})" for c, s in zip(r["kept_chunks"], r["kept_scores"])) or "—"
        lines.append(f"| {r['question_id']} | {r['config']} | {r['k']} | {chunks} | {dropped or 'none'} | "
                     f"{r['context_tokens']} | {r['retrieval_ok']} | {r['auto_correct']} | {short(r['answer'], 160)} |")
    (RAW_DIR / "rag_ksweep.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


EVAL_FIELDS = ["question_id", "type", "config", "retrieval_ok", "refused", "must_refuse",
               "format_ok", "auto_correct", "correct_answer", "grounded", "notes", "answer"]


def write_eval_sheet(runs):
    """One row per (question, config) of the main k=3 run.

    correct_answer and grounded are left blank for a human to fill with yes/no:
    whether an answer is right, and whether every claim is supported by the
    chunks it was given, needs reading, not string matching.

    If a previous rag_eval.csv exists, it is kept as rag_eval.prev.csv, and a
    row whose answer text is exactly the same as before keeps its human
    judgement (correct_answer, grounded, notes). Rows whose answer changed are
    left blank so they get judged again.
    """
    path = RAW_DIR / "rag_eval.csv"
    previous = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                previous[(row["question_id"], row["config"])] = row
        path.replace(RAW_DIR / "rag_eval.prev.csv")

    must = {q["id"]: q["must_refuse"] for q in load_questions()}
    carried, blank = 0, []
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVAL_FIELDS)
        w.writeheader()
        for r in runs:
            answer = " ".join(r["answer"].split())
            old = previous.get((r["question_id"], r["config"]))
            same = old is not None and " ".join(old["answer"].split()) == answer
            if same:
                carried += 1
            else:
                blank.append(f"{r['question_id']}-{r['config']}")
            w.writerow({"question_id": r["question_id"], "type": r["type"], "config": r["config"],
                        "retrieval_ok": r["retrieval_ok"], "refused": r["refused"],
                        "must_refuse": must[r["question_id"]], "format_ok": r["format_ok"],
                        "auto_correct": r["auto_correct"],
                        "correct_answer": old["correct_answer"] if same else "",
                        "grounded": old["grounded"] if same else "",
                        "notes": old["notes"] if same else "", "answer": answer})
    print(f"rag_eval.csv: kept the human judgement for {carried} unchanged answers; "
          f"needs judging: {', '.join(blank) or 'none'}")


def yes(value):
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


def summarize():
    """Evaluation table from rag_eval.csv (after the human columns are filled)."""
    with open(RAW_DIR / "rag_eval.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    pending = [r for r in rows if not r["correct_answer"].strip()
               or (r["config"] != "A" and not r["grounded"].strip())]
    if pending:
        print(f"WARNING: {len(pending)} rows still have empty correct_answer/grounded; "
              "auto_correct is used for correct_answer and grounded counts only filled rows.")

    lines = ["# RAG evaluation (k = 3)", "",
             "Accuracy = correct answers / 6 (for Q5/Q6 the correct answer is a refusal).  ",
             "Faithfulness = grounded / answers that were not refusals (B and C only).  ",
             "Format compliance = C answers that are the exact refusal sentence or cite valid [S#] sources.  ",
             "Robustness = Q5/Q6 refused, and Q1-Q4 not wrongly refused.", "",
             "| Config | Correct retrieval (Q1-Q4) | Accuracy | Faithfulness | Format compliance | Robustness: refused Q5/Q6 | Robustness: over-refusals Q1-Q4 |",
             "|---|---|---|---|---|---|---|"]
    per_q = ["", "| Q | Config | Retrieval | Correct | Grounded | Refused | Format |", "|---|---|---|---|---|---|---|"]
    for config in ["A", "B", "C"]:
        rs = [r for r in rows if r["config"] == config]
        correct = [yes(r["correct_answer"]) if r["correct_answer"].strip() else yes(r["auto_correct"]) for r in rs]
        retr = [r for r in rs if r["retrieval_ok"] not in ("", "None")]
        answered = [r for r in rs if not yes(r["refused"])]
        graded = [r for r in answered if r["grounded"].strip()]
        must = [r for r in rs if yes(r["must_refuse"])]
        should_answer = [r for r in rs if not yes(r["must_refuse"])]
        fmt = [r for r in rs if r["format_ok"] not in ("", "None")]
        def frac(subset, key):
            return f"{sum(yes(r[key]) for r in subset)}/{len(subset)}"

        retrieval_cell = frac(retr, "retrieval_ok") if retr else "n/a"
        if config == "A":
            faithful_cell = "n/a"
        else:
            faithful_cell = frac(graded, "grounded") if graded else "pending"
        format_cell = frac(fmt, "format_ok") if fmt else "n/a"
        lines.append(f"| {config} | {retrieval_cell} | {sum(correct)}/{len(rs)} | {faithful_cell} "
                     f"| {format_cell} | {frac(must, 'refused')} | {frac(should_answer, 'refused')} |")
        for r, c in zip(rs, correct):
            if r["grounded"].strip():
                grounded_cell = r["grounded"]
            elif config == "A":
                grounded_cell = "n/a"
            elif yes(r["refused"]):
                grounded_cell = "n/a (refused)"
            else:
                grounded_cell = "pending"
            per_q.append(f"| {r['question_id']} | {config} | {r['retrieval_ok']} | {c} | "
                         f"{grounded_cell} | {r['refused']} | {r['format_ok']} |")
    table = "\n".join(lines + per_q) + "\n"
    (RAW_DIR / "rag_eval_table.md").write_text(table, encoding="utf-8")
    print(table)


def load_questions():
    return yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--summary", action="store_true", help="build rag_eval_table.md from rag_eval.csv")
    args = parser.parse_args()
    if args.summary:
        summarize()
        return

    from model_client import ModelClient
    questions = load_questions()
    chunks, tokenizer = load_chunks()
    embedder = Embedder()
    t0 = time.perf_counter()
    store = VectorStore(chunks, embedder)
    print(f"indexed {len(chunks)} chunks from {len({c['source'] for c in chunks})} documents "
          f"in {time.perf_counter() - t0:.1f}s")
    check = store.self_check([q["question"] for q in questions])
    llm = ModelClient(model=LLM_MODEL, temperature=0.0)
    run_all(questions, store, tokenizer, llm, embedder.name, LLM_MODEL, check)


if __name__ == "__main__":
    main()
