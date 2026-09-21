"""
HW3 Part 2, step 3 - recompute the summary tables from raw/ only.

Reads:
  reports/hw03/raw/retrievals.jsonl
  reports/hw03/raw/chunk_stats.json
  reports/hw03/questions.yaml        expected_source for Recall@k
  reports/hw03/annotations.csv       your manual "does this chunk contain the answer?" labels

Writes the tables into reports/hw03/METRICS.md between the GENERATED markers
(everything you wrote outside the markers is kept) and prints them.

Metric definitions (per technique, averaged over the questions):
  Top-1 cosine   highest cosine_sim among the top-k of a question
  Mean@k cosine  mean cosine_sim of the top-k of a question
  Recall@k       share of questions with at least one top-k chunk from expected_source
  Latency        similarity-search time of a question (same value on all its k rows)

Run:  make rag-summary
      python code/rag_summary.py --init-annotations   (create annotations.csv to fill in)
"""
import argparse
import csv
import json
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
HW3 = ROOT / "reports" / "hw03"
RAW_DIR = HW3 / "raw"
QUESTIONS_FILE = HW3 / "questions.yaml"
ANNOTATIONS_FILE = HW3 / "annotations.csv"
METRICS_FILE = HW3 / "METRICS.md"

BEGIN = "<!-- BEGIN GENERATED (code/rag_summary.py) -->"
END = "<!-- END GENERATED -->"
TECHNIQUE_NAMES = {"token": "Token", "semantic": "Semantic", "sentence_window": "Sentence window"}


def load_data():
    # json.loads keeps chunk_hash as text (pd.read_json would turn "0123..." into a number)
    with open(RAW_DIR / "retrievals.jsonl", encoding="utf-8") as f:
        rows = pd.DataFrame([json.loads(line) for line in f if line.strip()])
    stats = pd.DataFrame(json.loads((RAW_DIR / "chunk_stats.json").read_text(encoding="utf-8")))
    questions = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]
    expected = {q["id"]: q["expected_source"] for q in questions}
    rows["hit"] = rows.apply(lambda r: r["source_file"] == expected[r["question_id"]], axis=1)
    return rows, stats, questions


def load_annotations():
    """annotations.csv -> {(technique, question_id, source_file, chunk_hash): 'yes'/'no'}

    source_file is part of the key because two recall notices can contain the
    exact same boilerplate sentence, i.e. the same chunk_hash."""
    labels = {}
    if not ANNOTATIONS_FILE.exists():
        return labels
    with open(ANNOTATIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            answer = row["contains_answer"].strip().lower()
            if answer in ("yes", "no"):
                key = (row["technique"], row["question_id"], row["source_file"], row["chunk_hash"])
                labels[key] = answer
    return labels


def summary_table(rows, stats):
    per_question = rows.groupby(["technique", "question_id"]).agg(
        top1_cosine=("cosine_sim", "max"),
        mean_k_cosine=("cosine_sim", "mean"),
        hit=("hit", "any"),
        latency_ms=("latency_ms", "first"),
    ).reset_index()

    per_technique = per_question.groupby("technique").agg(
        top1_cosine=("top1_cosine", "mean"),
        mean_k_cosine=("mean_k_cosine", "mean"),
        recall_k=("hit", "mean"),
        latency_ms=("latency_ms", "mean"),
    ).reset_index()

    table = stats[["technique", "n_chunks", "avg_chunk_len"]].merge(per_technique, on="technique")
    return table, per_question


def to_markdown(table, per_question, rows, labels, k):
    lines = [f"### Retrieval quality (k = {k}, averaged over {per_question['question_id'].nunique()} questions)", ""]
    lines.append(f"| Technique | Chunks | Avg chunk length (chars) | Top-1 cosine | Mean@{k} cosine | Recall@{k} | Mean retrieval latency (ms) |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, t in table.iterrows():
        lines.append(f"| {TECHNIQUE_NAMES[t['technique']]} | {t['n_chunks']} | {t['avg_chunk_len']:.1f} | "
                     f"{t['top1_cosine']:.4f} | {t['mean_k_cosine']:.4f} | {t['recall_k']:.2f} | {t['latency_ms']:.2f} |")

    lines += ["", "### Per question: top-1 cosine / expected source found in top-k", ""]
    qids = sorted(per_question["question_id"].unique())
    lines.append("| Technique | " + " | ".join(qids) + " |")
    lines.append("|---|" + "---|" * len(qids))
    for technique in TECHNIQUE_NAMES:
        cells = []
        for qid in qids:
            r = per_question[(per_question.technique == technique) & (per_question.question_id == qid)].iloc[0]
            cells.append(f"{r['top1_cosine']:.3f} {'hit' if r['hit'] else 'miss'}")
        lines.append(f"| {TECHNIQUE_NAMES[technique]} | " + " | ".join(cells) + " |")

    # Sanity check: the index's own score and our recomputed cosine should agree
    gap = (rows["store_score"] - rows["cosine_sim"]).abs().max()
    lines += ["", f"Largest |store_score - cosine_sim| over all {len(rows)} rows: {gap:.6f}"]

    # Confident but wrong: labelled "no" in annotations.csv, highest cosine first
    wrong = []
    for _, r in rows.iterrows():
        if labels.get((r["technique"], r["question_id"], r["source_file"], r["chunk_hash"])) == "no":
            wrong.append(r)
    lines += ["", "### Confidently scored chunks that do NOT contain the answer (from annotations.csv)", ""]
    if wrong:
        lines.append("| Technique | Question | Rank | Cosine | Source file | Preview |")
        lines.append("|---|---|---|---|---|---|")
        for r in sorted(wrong, key=lambda r: -r["cosine_sim"])[:10]:
            lines.append(f"| {TECHNIQUE_NAMES[r['technique']]} | {r['question_id']} | {r['rank']} | "
                         f"{r['cosine_sim']:.4f} | `{r['source_file']}` | {r['preview'][:90]} |")
    else:
        lines.append("_No chunk is labelled `no` in annotations.csv yet._")
    return "\n".join(lines)


def write_metrics(markdown):
    block = f"{BEGIN}\n{markdown}\n{END}"
    if METRICS_FILE.exists():
        text = METRICS_FILE.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            before = text.split(BEGIN)[0]
            after = text.split(END)[1]
            text = before + block + after
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = "# METRICS - Homework 3\n\n" + block + "\n"
    METRICS_FILE.write_text(text, encoding="utf-8")


def init_annotations(rows):
    """Write every retrieved chunk to annotations.csv with an empty contains_answer column."""
    if ANNOTATIONS_FILE.exists():
        print(f"{ANNOTATIONS_FILE} already exists - not overwriting your labels")
        return
    with open(ANNOTATIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["technique", "question_id", "rank", "cosine_sim", "chunk_hash",
                         "source_file", "contains_answer", "note", "preview"])
        for _, r in rows.sort_values(["question_id", "technique", "rank"]).iterrows():
            writer.writerow([r["technique"], r["question_id"], r["rank"], r["cosine_sim"],
                             r["chunk_hash"], r["source_file"], "", "", r["preview"]])
    print(f"wrote {len(rows)} rows to {ANNOTATIONS_FILE} - fill contains_answer with yes/no")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-annotations", action="store_true")
    args = parser.parse_args()

    rows, stats, _ = load_data()
    if args.init_annotations:
        init_annotations(rows)
        return

    table, per_question = summary_table(rows, stats)
    markdown = to_markdown(table, per_question, rows, load_annotations(), int(rows["k"].iloc[0]))
    print(markdown)
    write_metrics(markdown)
    print(f"\nupdated {METRICS_FILE}")


if __name__ == "__main__":
    main()
