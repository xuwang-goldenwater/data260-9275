# HW4 metrics

Hardware: MacBook Pro, Apple M1, 8 GB RAM · macOS · MySQL 8.0.43 · Python 3.12 (conda `data260`) · qwen3:8b via Ollama · embeddings all-MiniLM-L6-v2 (CPU)
Commit: _(tag hw4 hash)_

## Part 3 — N+1 measurement

Source: `raw/n1_requests.csv` (180 rows), `raw/n1_summary.json`, `raw/n1_table.md`.
30 measured requests per row after 5 warm-up requests; client-side latency over HTTP
on localhost; naive and fixed are paired on the same random page (seed 9275) and
interleaved, so both versions see the same rows and the same machine conditions.
"SQL stmts/req" is total / list-only; the constant difference of 2 is the session
check that every protected request pays (SELECT the session row, UPDATE its expiry).

| Page size | Version | SQL stmts/req (total / list) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| 10 | naive | 13 / 11 | 10.21 | 12.33 | 15.91 |
| 10 | fixed | 3 / 1 | 9.60 | 12.94 | 14.52 |
| 50 | naive | 53 / 51 | 19.33 | 20.98 | 22.33 |
| 50 | fixed | 3 / 1 | 10.53 | 12.52 | 23.29 |
| 200 | naive | 203 / 201 | 52.51 | 57.30 | 67.47 |
| 200 | fixed | 3 / 1 | 12.76 | 14.93 | 15.65 |

**Speed-up (naive p50 / fixed p50): page 10 = 1.06x, page 50 = 1.84x, page 200 = 4.12x.**
Measured on 2026-09-28 11:27 with the recall_date index present (it affects both versions equally).

Every naive/fixed pair returned identical JSON items (`same_items_as_other_version`
is True for all 180 rows), so the speed-up is not bought by returning less data.
With 30 samples, p99 is interpolated between the two slowest requests, so it is close
to the maximum and noisy (e.g. page 10: fixed p95 12.94 ms is above naive p95 12.33 ms, and
fixed at page 50 has p95 12.52 ms but p99 23.29 ms);
p50 is the number to compare.

**Why the speed-up grows with page size.** The naive endpoint sends 1 + N queries, so its time
grows linearly with N: from page 10 to page 200 its p50 rises from 10.2 to 52.5 ms, about
0.22 ms per extra row — the cost of one more round trip to MySQL plus building one ORM object.
The fixed endpoint sends one JOIN whatever N is, so it stays almost flat (9.6 → 12.8 ms; the
increase is serialising more rows). Both versions pay the same per-request overhead of roughly
9–10 ms (HTTP, the two session statements, FastAPI). At page 10 that overhead dominates and the
10 extra queries add little (1.06x); at page 200 the 200 extra round trips are most of the naive
request's time (4.12x). The speed-up is roughly (overhead + N × per-query cost) / overhead, so it
keeps growing with N, and it would be much larger with the database on another machine, where
each round trip costs milliseconds instead of a fraction of one.

## Part 3 — index

Index added (`code/sql/hw04_add_index.sql`):
`CREATE INDEX ix_recall_notices_recall_date ON recall_notices (recall_date);`
Query = the fixed list endpoint's SQL for page 1
(`… LEFT OUTER JOIN firms … ORDER BY recall_date DESC, id DESC LIMIT n`).
Source: `raw/explain_before_after.txt` / `.json`.

| Page size | Before: type / key / Extra | After: type / key / Extra | Median ms before → after (20 runs) |
|---|---|---|---|
| 10 | ALL / – / Using filesort | index / ix_recall_notices_recall_date / Backward index scan | 2.38 → 0.37 |
| 50 | ALL / – / Using filesort | ALL / – / Using filesort | 3.42 → 3.14 |
| 200 | ALL / – / Using filesort | ALL / – / Using filesort | 4.82 → 4.92 |

**What changed.** Without the index, MySQL has no ordered structure on recall_date, so for every
page it reads the whole table (type=ALL, "Table scan … rows=5001") and sorts it (Using filesort)
just to return the first N rows. With the index, the page-10 plan reads the index backwards and
stops after 10 entries (type=index, Backward index scan; estimated rows 4,970 → 10, optimizer cost
2,244 → 1,243). An InnoDB secondary index also stores the primary key, so (recall_date, id) is
already in the requested DESC, DESC order and no sort is needed: the median fell from 2.38 ms to
0.37 ms (6.4x faster). For page sizes 50 and 200 the optimizer kept the full scan even though the
index exists. The index holds only recall_date and id, so every row found through it needs a
second lookup to fetch product_name and category; on a 5,000-row table that fits in memory, one
sequential scan plus an in-memory sort is estimated cheaper than 50 or 200 random lookups (the
cost stays 2,244 before and after). The plans are identical, so the 3.42 → 3.14 ms and
4.82 → 4.92 ms differences are run-to-run noise. On a much larger table, or with a filter such
as WHERE recall_date >= … that selects a small range, the index would be chosen for every page size.

## Part 4 — RAG

Setup: 90 documents (89 FDA recall notices + 21 CFR Part 7, reused from HW3) →
182 chunks (SentenceSplitter, 500 tokens, overlap 50) → all-MiniLM-L6-v2 on CPU →
FAISS `IndexFlatIP` (cosine). Generator qwen3:8b, temperature 0.
Config C: candidate pool 2k → drop score < 0.35 → drop duplicates (same text or
cosine ≥ 0.92) → keep k → 1,600-token budget → label `[S1]…` with source and
chunk_id → grounding rules and the exact refusal sentence.
Source: `raw/rag_eval_table.md`, `raw/rag_eval.csv`, `raw/rag_comparison.md`.

### Evaluation (k = 3, six questions)

| Config | Correct retrieval (Q1–Q4) | Accuracy | Faithfulness | Format compliance | Refused Q5/Q6 | Wrong refusals Q1–Q4 |
|---|---|---|---|---|---|---|
| A — No RAG | n/a | 1/6 | n/a | n/a | 0/2 | 0/4 |
| B — Basic RAG | 3/4 | 5/6 | 1/5 | n/a | 1/2 | 0/4 |
| C — Context-engineered | 3/4 | 6/6 | 2/4 | 6/6 | 2/2 | 0/4 |

Accuracy = correct answers / 6, where the correct answer to Q5/Q6 is a refusal.
Faithfulness = answers supported by the chunks in the prompt / answers that were not
refusals (small denominators, so read these as counts, not rates). B's 1/5 includes Q6, which
it answered ("France") from three unrelated chunks.
Format compliance = C answers that are either the exact refusal sentence or cite only
valid `[S#]` numbers. Correct answer and grounded were judged by hand
(`raw/rag_eval.csv`); retrieval, refusal and format were checked by the script.

| Q (type) | A | B | C |
|---|---|---|---|
| Q1 one chunk | wrong ("saxitoxin") | correct, grounded | correct, grounded, cites [S1] |
| Q2 two chunks | wrong ("every 7 days") | correct, not grounded | correct, not grounded |
| Q3 across documents | incomplete | correct, not grounded | correct, grounded, cites [S1][S2] |
| Q4 ambiguous | generic advice | generic advice, not grounded | generic advice, not grounded |
| Q5 not in documents | hallucinated "$1.2 million" fine | refused | exact refusal (rules) |
| Q6 unrelated | answered ("Argentina") | answered wrongly ("France"), not grounded | exact refusal (threshold, no model call) |

### top_k sweep (Q2 and Q3, configs B and C)

Source: `raw/rag_ksweep.md`, `raw/rag_ksweep.json`. "Evidence retrieved" = every
evidence fragment for the question is in a chunk that went into the prompt.

| Q | Config | k | Chunks in prompt | Context tokens | Evidence retrieved | Result |
|---|---|---|---|---|---|---|
| Q2 | B | 1 | 1 | 477 | no | answered; Class I definition from model knowledge |
| Q2 | B | 3 | 3 | 1,336 | no | answered; definition chunk still missing |
| Q2 | B | 5 | 5 | 2,304 | **yes** | answered from both chunks |
| Q2 | C | 1 | 1 | 477 | no | refused (evidence insufficient) |
| Q2 | C | 3 | 3 | 1,336 | no | answered; only the status-report part cited |
| Q2 | C | 5 | 3 | 1,336 | no | token budget dropped chunks 4–5, including the definition |
| Q3 | B | 1 | 1 | 495 | no* | partial answer (one notice) |
| Q3 | B | 3 | 3 | 1,202 | yes | complete answer |
| Q3 | B | 5 | 5 | 2,157 | yes | complete answer, 2x the context of k = 3 |
| Q3 | C | 1 | 1 | 495 | no* | partial answer |
| Q3 | C | 3 | 3 | 1,202 | yes | complete, cited |
| Q3 | C | 5 | 4 | 1,596 | yes | complete; budget dropped 6 chunks |

\* the single Q3 chunk contains the Listeria paragraph with different wording from the
evidence fragment, so the string check marks it "no"; the answer is partial rather than wrong.

**Did more context help?** For Q2, yes: the Class I definition (21 CFR 7.3) ranks below
three other Part 7 chunks, so only k = 5 brought both needed chunks into B's prompt.
For Q3, k = 3 was enough; k = 5 added only more copies of the same Listeria paragraph
from other notices and nearly doubled the prompt (1,202 → 2,157 tokens) without
changing the answer. **Irrelevant chunks** appeared whenever the answer lived in fewer
chunks than k: Q2 at k = 3 (chunks on effectiveness checks in the recall strategy, § 7.42, and on firm-initiated recalls, § 7.46) and Q3 at k = 5.
**Best k:** 3 for Q3 and most questions; Q2 needed 5 in B, and in C it needs either a
larger token budget or smaller chunks — the 1,600-token budget that keeps C's prompts
short is exactly what dropped the definition chunk at k = 5.
