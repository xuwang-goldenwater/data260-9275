"""
HW3 Part 2, step 2 - compare three LlamaIndex chunking techniques (retrieval only).

For each technique (token / semantic / sentence_window):
  1. chunk the corpus in reports/hw03/corpus/
  2. build an in-memory VectorStoreIndex (SimpleVectorStore)
  3. for every question in reports/hw03/questions.yaml, retrieve the top-k chunks
     and print: query embedding (dimension + first 8 values), the shapes of the
     query vector and the stacked chunk vectors, and a table with
     rank / store_score / cosine_sim / chunk_len / preview

Output (machine-readable, read later by rag_summary.py):
  reports/hw03/raw/retrievals.jsonl         one line per technique x question x rank
  reports/hw03/raw/chunk_stats.json         one entry per technique
  reports/hw03/raw/query_embeddings.jsonl   dimension + first 8 values per question

Design decisions (see reports/hw03/METRICS.md):
  - cosine_sim is recomputed from the chunk text itself. For sentence_window the
    chunk is the single sentence that was indexed (the surrounding window is only
    metadata), so cosine_sim and chunk_len are measured on that sentence.
  - chunk_hash = sha256 of the chunk text. node_id is random on every run, the hash
    is not, so annotations.csv can point at a chunk and survive a re-run.

Run:  make run-rag        (commit questions.yaml first!)
"""
import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.node_parser import (
    SemanticSplitterNodeParser,
    SentenceWindowNodeParser,
    TokenTextSplitter,
)
from llama_index.core.schema import MetadataMode, QueryBundle

ROOT = Path(__file__).resolve().parent.parent
HW3 = ROOT / "reports" / "hw03"
CORPUS_DIR = HW3 / "corpus"
QUESTIONS_FILE = HW3 / "questions.yaml"
RAW_DIR = HW3 / "raw"

SEED = 9275
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
TOP_K = 5

# Chunking parameters. all-MiniLM-L6-v2 only reads the first 256 word pieces of a
# text, so the token chunks are kept below that.
TOKEN_CHUNK_SIZE = 200
TOKEN_CHUNK_OVERLAP = 30
SEMANTIC_BUFFER_SIZE = 1
SEMANTIC_BREAKPOINT_PERCENTILE = 95
WINDOW_SIZE = 3

def make_embed_model():
    # Imported here so the rest of the file can be read/tested without torch.
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    return HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)


def load_documents():
    """One Document per corpus file. The file name is kept as metadata but is NOT
    embedded, so a chunk's embedding depends on its text only."""
    documents = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        documents.append(Document(
            text=path.read_text(encoding="utf-8"),
            metadata={"source_file": path.name},
            excluded_embed_metadata_keys=["source_file"],
            excluded_llm_metadata_keys=["source_file"],
        ))
    return documents


def load_questions():
    return yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))["questions"]


def chunk_documents(technique, documents, embed_model):
    """Step 1 - the only step that differs between the three techniques."""
    if technique == "token":
        params = {"chunk_size": TOKEN_CHUNK_SIZE, "chunk_overlap": TOKEN_CHUNK_OVERLAP}
        parser = TokenTextSplitter(**params)
    elif technique == "semantic":
        params = {"buffer_size": SEMANTIC_BUFFER_SIZE,
                  "breakpoint_percentile_threshold": SEMANTIC_BREAKPOINT_PERCENTILE}
        parser = SemanticSplitterNodeParser(embed_model=embed_model, **params)
    elif technique == "sentence_window":
        params = {"window_size": WINDOW_SIZE}
        parser = SentenceWindowNodeParser.from_defaults(
            window_size=WINDOW_SIZE,
            window_metadata_key="window",
            original_text_metadata_key="original_text",
        )
    else:
        raise ValueError(technique)
    nodes = parser.get_nodes_from_documents(documents)
    return nodes, params


def chunk_text(node):
    """The exact text that was embedded for this chunk."""
    return node.get_content(metadata_mode=MetadataMode.EMBED)


def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def retrieve(index, embed_model, technique, question_id, question, k=TOP_K):
    """Step 3 - retrieval-only helper. Prints everything and returns one row per hit."""
    # Query embedding
    query_vec = np.array(embed_model.get_query_embedding(question))
    print(f"\n[{technique}] {question_id}: {question}")
    print(f"query embedding dim = {query_vec.shape[0]}, first 8 = {np.round(query_vec[:8], 4).tolist()}")

    # Similarity search only. The query is already embedded, so the timer
    # measures the search, not the embedding model.
    retriever = index.as_retriever(similarity_top_k=k)
    start = time.perf_counter()
    hits = retriever.retrieve(QueryBundle(query_str=question, embedding=query_vec.tolist()))
    latency_ms = (time.perf_counter() - start) * 1000

    # Embed the returned chunks again, explicitly, and compare with the query
    texts = [chunk_text(hit.node) for hit in hits]
    doc_vecs = np.array(embed_model.get_text_embedding_batch(texts))
    print(f"query vector shape = {query_vec.shape}, stacked chunk vectors shape = {doc_vecs.shape}")
    print(f"similarity search took {latency_ms:.2f} ms")

    run_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for rank, (hit, text, vec) in enumerate(zip(hits, texts, doc_vecs), start=1):
        rows.append({
            "technique": technique,
            "question_id": question_id,
            "k": k,
            "rank": rank,
            "store_score": round(float(hit.score), 6),
            "cosine_sim": round(cosine(query_vec, vec), 6),
            "node_id": hit.node.node_id,
            "chunk_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "source_file": hit.node.metadata["source_file"],
            "chunk_len": len(text),
            "preview": " ".join(text.split())[:160],
            "latency_ms": round(latency_ms, 3),
            "run_at": run_at,
        })

    # The table the assignment asks for
    print(f"{'rank':>4}  {'store_score':>11}  {'cosine_sim':>10}  {'chunk_len':>9}  {'source_file':<45}  preview")
    for r in rows:
        print(f"{r['rank']:>4}  {r['store_score']:>11.4f}  {r['cosine_sim']:>10.4f}  {r['chunk_len']:>9}  "
              f"{r['source_file'][:45]:<45}  {r['preview']}")
    return rows, {"question_id": question_id, "dim": int(query_vec.shape[0]),
                  "first_8": np.round(query_vec[:8], 6).tolist()}


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    embed_model = make_embed_model()
    Settings.embed_model = embed_model   # never fall back to the OpenAI default
    Settings.llm = None                  # retrieval only, no LLM

    documents = load_documents()
    questions = load_questions()
    print(f"corpus: {len(documents)} files, {sum(len(d.text) for d in documents):,} characters")
    print(f"questions: {len(questions)}, top-k = {TOP_K}, embed model = {EMBED_MODEL_NAME}")

    all_rows, all_stats, query_info = [], [], {}
    for technique in ["token", "semantic", "sentence_window"]:
        print("\n" + "=" * 100)
        print(f"TECHNIQUE: {technique}")
        print("=" * 100)

        # 1. Chunking
        start = time.perf_counter()
        nodes, params = chunk_documents(technique, documents, embed_model)
        lengths = [len(chunk_text(n)) for n in nodes]
        # 2. Indexing (in memory, SimpleVectorStore is the default)
        index = VectorStoreIndex(nodes, embed_model=embed_model)
        build_s = time.perf_counter() - start
        print(f"{len(nodes)} chunks, avg length {np.mean(lengths):.1f} chars, "
              f"built in {build_s:.1f} s, params {params}")

        all_stats.append({
            "technique": technique,
            "n_chunks": len(nodes),
            "avg_chunk_len": round(float(np.mean(lengths)), 1),
            "min_chunk_len": int(np.min(lengths)),
            "max_chunk_len": int(np.max(lengths)),
            "len_unit": "chars",
            "params": params,
            "embed_model": EMBED_MODEL_NAME,
            "embed_dim": len(embed_model.get_query_embedding("dimension check")),
            "chunk_and_index_seconds": round(build_s, 2),
        })

        # 3. Retrieval for every question
        for q in questions:
            rows, info = retrieve(index, embed_model, technique, q["id"], q["question"])
            all_rows.extend(rows)
            query_info[q["id"]] = info

    with open(RAW_DIR / "retrievals.jsonl", "w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (RAW_DIR / "chunk_stats.json").write_text(json.dumps(all_stats, indent=2), encoding="utf-8")
    with open(RAW_DIR / "query_embeddings.jsonl", "w", encoding="utf-8") as f:
        for info in query_info.values():
            f.write(json.dumps(info) + "\n")

    print(f"\nwrote {len(all_rows)} rows to {RAW_DIR / 'retrievals.jsonl'}")
    print("next: make rag-summary")


if __name__ == "__main__":
    main()
