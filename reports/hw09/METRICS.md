# HW9 Metrics - Xu Wang (SID4 9275)

SID4 9275 · PORT_BASE 8275 · PREFIX s9275 · SEED 9275 · VERIFY_SEED 269275 · DOMAIN_ID 3 (Grocery supply and recall notices)
Hardware: MacBook Pro, Apple M1, 8 GB · Redis: redis/redis-stack-server 7.4.0-v1 (Docker, 127.0.0.1:6379) · MySQL 8.0 `s9275_rel`
Embedding: sentence-transformers/all-MiniLM-L6-v2 on CPU (384 dims, unit length) · Model: qwen2.5:3b via Ollama (temperature 0, seed 9275)
All runs on 2026-11-06. Raw evidence: `raw/` (Parts 1-3) and `part4/` (Part 4). Self-check: `verification.json` (35 passed, 0 failed).

## Part 1 - Redis view counter

`RecallCache.increment_recall_notice_views(notice_id)`: `INCR s9275:views:recall_notice:<id>`; when `count % 10 == 0`, `UPDATE recall_notices SET view_count = count` (with `updated_at = updated_at`, so a view does not count as a change to the notice).

| Accesses | Redis count | MySQL `view_count` | SQL writes |
|---|---|---|---|
| 25 on notice 1 | 25 | 20 (synced at 10 and 20) | 2 instead of 25 |

The database lags Redis by up to 9 views. If the Redis container is rebuilt, the counter restarts at 1 while MySQL still holds the last synced value.

## Part 2 - semantic cache (threshold 0.85, no recall guard)

Ingress `SemanticCache.ask()`: embed -> KNN 1 in Redis (FLAT, COSINE; similarity = 1 - distance) -> hit: stored final answer / miss: database facts + HW8 Planner -> Writer -> Reviewer over Kafka, store only `approved` answers. Entry `s9275:semcache:<sha1>` = query, embedding, answer, notice_id, data_version, created_at.

| # | kind | is_cached | similarity | latency ms |
|---|---|---|---|---|
| 1 | new | False | - | 16885.4 |
| 2 | duplicate | True | 1.0000 | 252.1 |
| 3 | paraphrase | True | 0.9717 | 21.5 |
| 4 | new | False | 0.7265 | 24641.5 |
| 5 | paraphrase | True | 0.9356 | 294.7 |
| 6 | new | False | 0.4278 | 18268.6 |
| 7 | paraphrase | True | 0.9783 | 287.9 |
| 8 | duplicate | True | 1.0000 | 21.3 |
| 9 | new | **True (false hit)** | 0.8518 | 13.6 |
| 10 | duplicate | True | 1.0000 | 17.1 |
| 11 | new | False | 0.5655 | 17896.9 |
| 12 | paraphrase | False | 0.7500 | 23077.5 |

- **Cache hit rate: 7/12 = 58.3%**
- **Average latency: cached 129.7 ms (n=7, median 21.5 ms) vs not cached 20,154.0 ms (n=5)**
- Redis search itself took 1.2-3.0 ms on every hit; the rest is embedding. The three 250-295 ms hits each came right after a 17-25 s model call (first encode after the agents ran).
- Q9 "When was recall F-0003-2023 issued?" hit "Which firm issued recall F-0002-2021?" and returned another recall's firm - a false hit at 0.85 before Part 3 began. Q12 then missed correctly: F-0003-2023 had never been answered.
- Found while testing: the HW8 Reviewer (qwen2.5:3b) rejected a correct answer twice ("does not explicitly state the number of units", the draft said 8019) because it could not see the database facts. Fix: the Reviewer gets the same facts as the Writer, plus a rule that rejects numbers not in the facts. The Writer still sometimes adds a recall reason that is not in the facts; the numbers rule does not catch that.

## Part 3 - threshold economics and stale answers

### 3.1 Labeled set
`cache_cases.yaml`: 10 seeds (6 record questions, one field each; 4 general questions) and 40 cases - 10 exact, 10 paraphrase (expect hit on own seed), 10 superficially similar (other recall number / other field / other audience, expect miss), 10 unrelated. Committed in 4188961, before the sweep (93e295a), never edited (checked by verify_hw09).

### 3.2 Threshold sweep
Prepare once: the 10 seeds answered by the agents and cached (all approved on the first try); each of the other 30 cases run through the agents once, not stored, for its correct answer and real miss latency (mean agent time over the 40 cases 18.4 s). Sweep: cache frozen at the 10 seeds; at each threshold every case is embedded and searched for real; a miss adds that case's measured agent time.
False-hit rate = false hits / hits. Total cost from 3.4 (miss = 1, false hit = 20).

| Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost |
|---|---|---|---|---|
| 0.75 | 75.0% (30/40) | 36.7% (11/30) | 3394.9 | 230 |
| 0.80 | 70.0% (28/40) | 35.7% (10/28) | 4300.7 | 212 |
| 0.85 | 62.5% (25/40) | 28.0% (7/25) | 5703.9 | 155 |
| 0.90 | 57.5% (23/40) | 21.7% (5/23) | 6538.8 | 117 |
| 0.95 | 40.0% (16/40) | 18.8% (3/16) | 9693.2 | 84 |

The superficially similar record questions (same wording, other recall number) scored 0.93-0.98 - higher than some real paraphrases (P04 0.77, P06 0.91). No threshold separates them: at 0.95 three wrong recalls are still served while 7 correct hits are already lost. The general-question look-alikes scored 0.79-0.88, so 0.90 removes all of them.

### 3.3 One false hit in full (M03, survives every threshold)
- Cached query (S3): "What is the recall date of F-0003-2023?"
- Incoming query (M03): "What is the recall date of F-0001-2025?"
- Similarity: **0.9758**
- Cached answer returned: "The recall date for F-0003-2023 is 2023-12-29. This specific date is mentioned in the recall notice for the Sunrise Valley Tahini, 6-pack batch affected by mislabeling from Harbor Mills Inc. in Georgia."
- Correct answer: 2025-06-23 (F-0001-2025, Blue Heron Enoki Mushrooms, 32 oz tub, Harbor Snacks Co.) - from the agents' own answer to M03 and the database row.
- Why the embedding confused them: the two sentences are identical except for the recall number. MiniLM splits "F-0003-2023" and "F-0001-2025" into short word pieces ("f", "-", "000", "##3", ...) that differ in two pieces only, and mean pooling averages those few tokens with a dozen identical ones. The model was trained to match meaning, and to it both sentences ask the same thing - "the date of a recall"; the identifier that decides the answer carries almost no weight in the vector.

### 3.4 Cost model and threshold choice
- **Miss cost = 1**: one full pipeline run (3 qwen2.5:3b calls, 18.4 s of local model time on average). Every miss pays it.
- **False-hit cost = 20**: a store receives facts for the wrong recall (date, firm, units, product). It may pull the wrong product or keep selling the recalled one - a support ticket plus a food-safety exposure, far more than 20 s of compute. A correct hit costs 0.
- Total cost = misses x 1 + false hits x 20 (column above). With threshold only, 0.95 is cheapest (84) and stays the choice for any false-hit cost >= 4; but it still serves 3 wrong recalls.
- Added control: **recall-number guard** - a hit is allowed only if the incoming and the cached question name the same recall number (no constraint when neither names one). Same cases, same measured similarities and agent times:

| Threshold + guard | Hit rate | False-hit rate | Mean latency (ms) | Misses | False hits | Total cost |
|---|---|---|---|---|---|---|
| 0.75 | 57.5% | 17.4% | 6907.1 | 17 | 4 | 97 |
| 0.80 | 52.5% | 14.3% | 7812.9 | 19 | 3 | 79 |
| 0.85 | 50.0% | 10.0% | 8214.3 | 20 | 2 | 60 |
| **0.90** | **45.0%** | **0.0%** | **9049.1** | **22** | **0** | **22** |
| 0.95 | 32.5% | 0.0% | 11215.1 | 27 | 0 | 27 |

**Shipped: threshold 0.90 + recall-number guard** (18 correct hits, 0 false hits, cost 22). The threshold handles closeness of meaning; the guard handles the identity of the record, which the embedding cannot see. 0.90 rather than 0.95 because the guard already removes the dangerous hits and 0.95 throws away 5 more correct ones.

### 3.5 Stale answers and invalidation
Record F-0001-2025 (`recall_notices.id = 1`), cached seed S1 "How many units were affected by recall F-0001-2025?".

| Step | What happened | Answer says | Database | is_cached | Latency |
|---|---|---|---|---|---|
| 1 | ask S1 | 8019 | 8019 (version 0) | True | 57.1 ms |
| 2 | write path: units 8019 -> 8500, version 0 -> 1 | | 8500 | | |
| 3 | ask, VERSION_CHECK off | **8019 (stale hit)** | 8500 | True | 16.1 ms |
| 4 | ask, VERSION_CHECK on: `v0 != v1` -> entry deleted -> agents | 8500 | 8500 | False | 29451.3 ms |
| 5 | ask again | 8500 | 8500 | True | 304.1 ms |
| 6 | restore 8019, version 1 -> 2 | | 8019 | | |

Strategy: per-record data version in Redis (`s9275:ver:recall_notice:<id>`); every cache entry stores the version its answer was built from; the write path bumps the version; a hit with a different version is deleted and treated as a miss (lazy invalidation).
Trade-off: a hit pays only one extra Redis GET (no database read) and only answers about the changed record are invalidated - but every write path must bump the version. An `UPDATE` that bypasses the application (manual SQL, an old Postman request) leaves stale answers in place, general answers with no record are not covered (they would need a TTL), and outdated entries use memory until they are hit.

### Label notes (cache_cases.yaml not edited)
- P05 "Why was the product in recall F-2015-2026 recalled?" was labeled a paraphrase of S5 (recall category). MiniLM put it closest to S4 (0.8436), so it counts as a false hit at 0.75 / 0.80 under the definitions. "Why" is wider than "category"; I would label it ambiguous today, but the label stays as committed.

## Part 4 - self-improving two-agent system

Reference: `part4/reference_notices.json` - 30 records from `s9275_rel` (Random(9275), HW4-seeded rows only), split 10/10/10 so test questions never ask about a record seen in training or validation. Inputs (id + question only): training 10, validation 10, test 12, each mixing single-field, two-field, not-found recall numbers and off-domain questions.
Answering Agent: qwen2.5:3b, its own database lookup (HW5 MySQLRepo.get), plain help-desk system prompt; lessons go into the system message. Evaluator Agent: deterministic, checks every asked field against the reference, flags numbers not in the record, requires "not found" for unknown numbers and a decline for off-domain questions; feedback names the field, never the value. Stop at PASS or after 2 attempts.

### Training (4.1 / 4.2) - 9/10 PASS
| Question | Attempt 1 | Attempt 2 | Note |
|---|---|---|---|
| train_05 (controlled: units hidden on attempt 1) | REVISE - units_affected missing ("affecting 6-pack units") | PASS - 9216 units | evaluator feedback -> revision |
| train_01 capital of France | REVISE - answered | PASS - declined | |
| train_04 unknown F-7258-2022 | REVISE - implied the record exists | PASS - "does not exist" | fabricated_not_found x1, no lesson |
| train_07 boil an egg | REVISE - answered | **REVISE** - declined, then answered anyway | 2nd answered_off_domain -> **lesson_001** |

lesson_001 (`answered_off_domain`, from train_01 + train_07): "Reply that you can only answer questions about grocery recall notices. Do not answer the question itself."

### Validation (4.3) - lesson_001 KEPT
| Run | Lesson placement | PASS without -> with | Fixed | Regressions | val_10 with the lesson |
|---|---|---|---|---|---|
| 1 | end of the user message | 8/10 -> 8/10 | - | - | "...written by Jane Austen." (ignored) |
| 2 (kept) | system message | 9/10 -> 9/10 | - | - | "I can only answer questions related to grocery recall notices. Pride and Prejudice was written by Jane Austen." (declined, then answered) |

Run 2 also includes an evaluator fix for val_06 ("does not contain any recall notice" is a correct not-found answer). The lesson met all three rules (failures unchanged, no regressions, no new unsupported answers on unrelated questions) and was kept; it changed the behaviour but did not yet turn val_10 into a pass.

### Final test (4.4) - test_data.json, 12 questions, run once after the lesson was selected
| Variant | Correct answers | Incorrect answers | Average attempts | Average latency |
|---|---|---|---|---|
| Baseline | 8 | 4 | 1.00 | 4.52 s |
| Evaluator Repair | 11 | 1 | 1.33 | 4.91 s |
| Lesson Memory | 11 | 1 | 1.25 | 4.71 s |
| Validated Improvement | 11 | 1 | 1.25 | 5.14 s |

- Baseline fails both off-domain questions and both unknown recall numbers. Repair fixes three of the four; test_10 (guitar) repeats the same answer and stays wrong.
- With lesson_001, test_10 declines correctly on the first attempt.
- Manual review: in both lesson variants test_02 ("How many planets...") answered "I can only answer questions related to grocery recall notices. The question about the number of planets in the solar system is not relevant to this database." That is a correct decline; the evaluator marked it REVISE because "not relevant" is not in its decline phrase list. The table above is the automatic result and was not re-run; by manual review both lesson variants are 12/12.
- Lesson Memory and Validated Improvement are the same configuration in this run: validation removed no lesson, so "all saved lessons" and "only validated lessons" are both {lesson_001}. Their latency difference is run-to-run noise.
