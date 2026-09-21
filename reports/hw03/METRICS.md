# METRICS — Homework 3, Part 2

Corpus: 89 FDA food recall announcements + 21 CFR Part 7 (see SOURCES.md).
Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions).
Index: LlamaIndex `VectorStoreIndex`, in-memory `SimpleVectorStore`. k = 5.

| Technique | Parameters |
|---|---|
| Token | `TokenTextSplitter(chunk_size=200, chunk_overlap=30)` |
| Semantic | `SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=95)` |
| Sentence window | `SentenceWindowNodeParser(window_size=3)` |

Measurement choices:

- `cosine_sim` is recomputed from the chunk text. For sentence window, the
  chunk is the single indexed sentence (the window is metadata only), so
  cosine and length are measured on that sentence.
- Recall@k = share of questions where at least one top-k chunk comes from the
  question's `expected_source` in questions.yaml.
- Latency = similarity search only; the query is embedded before the timer starts.

Everything between the GENERATED markers is rewritten by `make rag-summary`.

<!-- BEGIN GENERATED (code/rag_summary.py) -->
_Run `make run-rag` and `make rag-summary` to fill this in._
<!-- END GENERATED -->

## Confidently scored retrieval without the answer

TODO after the run: pick one row from the table above and explain why the
embedding found it similar.

## Observations

TODO (1–2 short paragraphs).

## Conclusion

TODO (2–5 sentences).
