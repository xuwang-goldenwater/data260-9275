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
### Retrieval quality (k = 5, averaged over 5 questions)

| Technique | Chunks | Avg chunk length (chars) | Top-1 cosine | Mean@5 cosine | Recall@5 | Mean retrieval latency (ms) |
|---|---|---|---|---|---|---|
| Token | 413 | 760.3 | 0.7085 | 0.6488 | 1.00 | 9.43 |
| Semantic | 204 | 1339.3 | 0.6867 | 0.6035 | 1.00 | 4.60 |
| Sentence window | 1706 | 160.2 | 0.7467 | 0.6817 | 0.80 | 29.85 |

### Per question: top-1 cosine / expected source found in top-k

| Technique | q1 | q2 | q3 | q4 | q5 |
|---|---|---|---|---|---|
| Token | 0.691 hit | 0.769 hit | 0.649 hit | 0.769 hit | 0.666 hit |
| Semantic | 0.653 hit | 0.651 hit | 0.654 hit | 0.802 hit | 0.673 hit |
| Sentence window | 0.798 hit | 0.780 hit | 0.656 hit | 0.770 hit | 0.730 miss |

Largest |store_score - cosine_sim| over all 75 rows: 0.000001

### Confidently scored chunks that do NOT contain the answer (from annotations.csv)

| Technique | Question | Rank | Cosine | Source file | Preview |
|---|---|---|---|---|---|
| Sentence window | q1 | 1 | 0.7979 | `ecfr_21cfr_part7.txt` | (b) On the basis of this determination, the Food and Drug Administration will assign the r |
| Sentence window | q1 | 2 | 0.7830 | `ecfr_21cfr_part7.txt` | (m) Recall classification means the numerical designation, i.e., I, II, or III, assigned b |
| Sentence window | q5 | 1 | 0.7301 | `fda_frito-lay-issues-voluntary-allergy-alert.txt` | Those with an allergy or severe sensitivity to milk run the risk of a serious or life-thre |
| Sentence window | q5 | 2 | 0.7239 | `fda_sugar-foods-issues-recall-specific-lots.txt` | Out of an abundance of caution, and because this milk powder was used in a seasoning ingre |
| Semantic | q1 | 1 | 0.6535 | `fda_fresh-ready-foods-llc-recalls-spicy.txt` | ET. This recall is being conducted in cooperation with the FDA. |
<!-- END GENERATED -->

## Confidently scored retrieval without the answer

Sentence window, q5, rank 1, cosine 0.7301, `fda_frito-lay-issues-voluntary-allergy-alert.txt`:
"Those with an allergy or severe sensitivity to milk run the risk of a serious or life-threatening allergic reaction..."

q5 asks which milk was recalled because of food-grade cleaning agents. This sentence is an allergy warning from a
Frito-Lay recall. It shares the words "milk" and "recall" with the question, and the same sentence appears in many
allergen notices, so its vector is close to the query. The words "cleaning agents" appear in only one document, and
they do not pull the query vector enough. A second case: sentence window, q1, rank 1 (cosine 0.7979, the highest of
the run) comes from the right file but only says that FDA assigns a class; it does not say what Class II means.

## Observations

Token chunking worked best overall in my test. It found the right source file for all 5 questions (Recall@5 = 1.00), and its Mean@5 cosine was 0.649.

Sentence-window got the highest top-1 cosine (0.747), but its recall was the lowest (0.80). It missed q5 completely. For q5 (the milk with cleaning agents), all 5 results were from other recalls, for example a sentence about people with a milk allergy. For q1, the top 2 results were from the right file (21 CFR Part 7), but they did not have the Class II definition in them. So a high cosine score does not always mean the answer is there. A short sentence with common words like "milk" or "recall" can get a high score even if it does not answer the question.

Semantic chunking also found the right file for all 5 questions (Recall@5 = 1.00), but its top-1 cosine was the lowest (0.687). Its chunk sizes were very uneven. The longest chunk had 11,491 characters, which is much longer than what MiniLM can read (about 256 word pieces), so most of that chunk was cut off when it was embedded. Some other chunks were only one short sentence, like "This recall is being conducted in cooperation with the FDA." One of these was ranked first for q1 even though it had no useful information.

The best technique was not the same for every question. On q5, semantic chunking ranked the correct document first, and sentence-window failed. On q1 and q2, sentence-window gave the highest scores.

Sentence-window was also the slowest (29.85 ms per search), because it made the most chunks (1,706).

## Conclusion

For this corpus, I think token chunking is the best choice. It had perfect recall, and its chunks were a similar size, so each chunk kept enough context. I also learned that cosine similarity alone is not a good way to judge retrieval. It is better to check whether the retrieved chunks really contain the answer.
