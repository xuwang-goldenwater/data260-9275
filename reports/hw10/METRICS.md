# HW10 Metrics - Xu Wang (SID4 9275)

SID4 9275 · PORT_BASE 8275 · PREFIX s9275 · SEED 9275 · VERIFY_SEED 269275 · DOMAIN_ID 3 (Grocery supply and recall notices)
Hardware: MacBook Pro, Apple M1, 8 GB · Kafka 3.8 (KRaft, Docker) · Redis Stack 7.4 · MySQL 8.0 `s9275_rel`
Agents (HW8 Planner / Writer / Reviewer): qwen2.5:3b via Ollama, temperature 0, seed 9275
Judge: **qwen3:4b via Ollama (local)**, DeepEval 4.3.4 GEval, temperature 0, seed 9275, num_ctx 4096, num_predict 300, think off, JSON-schema output, 90 s timeout, 1-5 rubric
All runs on 2026-11-13. Raw evidence: `raw/` (Parts 1, 2, 4) and `part3/`. Self-check: `verification.json` (23 passed, 0 failed).

Built in the order 4 → 2 → 3 → 1: the evaluator writes spans (Part 4), the 20 judge-validation drafts come from the 50-request latency run (Part 4.3), and the dashboard reads all of them. Sections below follow the assignment order.

## Part 1 - Streamlit operations dashboard

`streamlit run code/ops_dashboard/app.py` (make `hw10-dashboard`). Three pages: Summary, Evaluation, Trace lookup. Every number is read from the evidence files of Parts 2-4 (below), and each metric states its source file and time window. `@st.cache_data` for file reads (keyed on file modification time, ttl 30 s), `@st.cache_resource` for the Redis connection.

Summary over all recorded requests (2026-11-13 09:01-11:01): 61 requests = 50 latency misses + 1 failed demo + 10 cache hits (one in the trace demo, nine repeated afterwards so the hit latency has n = 10). Hit rate 16.4% (10/61), error rate 1.6% (1/61, the injected failure), Reviewer rejection rate 15.7% (8/51 misses). The hit rate is low by design: the 50 latency requests were chosen to miss.

## Part 2 - evaluator on the Kafka pipeline

`code/eval_pipeline/evaluator.py`: a separate consumer group `s9275_evaluator` on `s9275_tasks`, `s9275_drafts`, `s9275_final`, joining plan / draft / final on `correlation_id`. Each result (`raw/eval_results.jsonl`) keeps the question, facts, plan, draft, final, Reviewer verdict and reason, the topic / partition / offset / timestamp of the three source messages, the judge settings and every score with its reason.
Bounded: join timeout 120 s (status `incomplete` + error span), 90 s per judge call, `num_predict` 300, malformed messages skipped; a judge failure is recorded per metric.

Judge choice: qwen3:8b was tried first; on 8 GB it ran 24% on CPU and a 5-token reply took 81.5 s (a JSON reply did not finish in 300 s). qwen3:4b runs 100% on GPU, about 12 s per score. It is a different model from the generator (qwen2.5:3b).

All 50 latency requests of Part 4.3 were evaluated (1-5):

| Kind | n | Reviewer approved | Plan quality | Writer draft | Final answer |
|---|---|---|---|---|---|
| record | 38 | 32 | 2.63 | 4.42 | 4.42 |
| not found | 6 | 5 | 2.33 | 2.17 | 2.17 |
| off-domain | 6 | 5 | 2.50 | 1.00 | 1.00 |
| **all** | **50** | **42** | **2.58** | **3.74** | **3.74** |

Final vs draft: the final text was identical to the draft in **50/50** traces, difference **0** on every trace. The final answer did not improve.

What this says about coordination:
- **Planner → Writer:** plans score low (2.58) while drafts score higher (3.74). The Writer's answer comes from the database facts the gateway attaches, not from the plan; the Planner is the slowest stage (40% of a miss, Part 4.3) and adds little.
- **Writer → Reviewer:** the Reviewer approves or rejects but never rewrites (`answer = draft`). No improvement is possible by design, which is what the scores show - it is not a judge artefact.
- **Reviewer as a gate:** drafts it rejected scored higher (mean 4.25, n = 8) than drafts it approved (3.64, n = 42); 6 rejected drafts scored 5. Example: it rejected the correct "recall F-0004-2022 was not found" answer. The gate is not aligned with answer quality.
- Caveat from Part 3: the judge is reliable only on record questions; the not-found and off-domain scores above are mostly judge error.

## Part 3 - judge validation

`reports/hw10/eval_cases.json`: 20 Writer drafts from the Part 4.3 latency run, chosen without looking at judge scores (stratified by kind and Reviewer verdict: 6 approved + 6 rejected record questions, 4 not-found, 4 off-domain; random.Random(9275)). `human_labels.csv`: my labels, assigned from `labeling_sheet.md` (question, facts, draft, same 1-5 rubric as the judge, no scores). Both committed in **134994a**, before `validate_judge.py` existed; the judge results are in 957ff97. These drafts had been scored once in Part 2 as part of the pipeline evaluation; I labelled from the sheet, not from those results. The judge runs below are new.

### 3.2 Judge vs human (`part3/judge_runs.csv` has every score)

| Metric | Value |
|---|---|
| Spearman rho | **0.265** (p = 0.26, not significant) |
| Mean absolute difference | **1.35** points |
| Judge - human (mean) | -0.75 (judge is harsher) |
| Exact agreement / within 1 point | 30% / 65% |

| Kind | n | mean \|judge - human\| |
|---|---|---|
| record | 12 | 0.67 |
| off-domain | 4 | 1.75 |
| not found | 4 | **3.00** |

Why they disagree (from `part3/judge_reasons.jsonl`):
1. The rubric's lowest band says "does not answer the question"; for a recall that does not exist the correct answer is "not found". The judge applied band 1 anyway (c06: "does not answer the question (which asks for the state)" → 1; my label 5), although evaluation step 4 says the opposite.
2. For off-domain questions the judge gets the context "No database record was looked up" and reads it as "everything in the answer is unsupported" (c05, Python/JavaScript for "which language to learn first" → "invents languages" → 1).
3. Some reasons describe text that is not in the draft (c17: "includes extra details like product name and category" - the draft is one sentence with the firm and the state).
12 of my 20 labels are 5, so the human scores have many ties, which also lowers rho.

### 3.3 Repeatability (3 runs, same inputs, same settings)

| | |
|---|---|
| Cases whose score changed | **0 / 20** |
| Run pairs that differ | 0 / 60 |
| Mean / max absolute change | 0 / 0 |
| Judge errors | 0 |

With temperature 0 and a fixed seed the judge is deterministic - including the same reasons.

**Would I let this judge gate a deployment? No.** It is perfectly repeatable but consistently wrong on two of the three answer kinds; repeatability without validity just repeats the error. Before trusting it I would need: (1) a rubric that states "not found" and a polite decline are correct answers, and a clearer context for off-domain questions; (2) a new labelled set, never seen while changing the rubric, with at least ~20 cases per kind and per-kind agreement reported; (3) a second human labeller, to know the human-human agreement the judge should reach; (4) a check that the judge's reasons match the draft; (5) a comparison with a stronger judge model. I did not change the rubric after seeing these results: tuning it on the same 20 drafts would make the validation meaningless.

## Part 4 - distributed tracing and latency analysis

`trace_id` = the HW8 `correlation_id`, created once at the start of `SemanticCache.ask()`, **before** the cache lookup (in HW9 it was created only after a miss, so a cache hit had no id). Every stage writes one JSON line to `raw/spans.jsonl` through `code/observability/tracing.py`:
`trace_id, stage, start_ts, end_ts, duration_ms, status, error` (+ `cache`, `hop`, `review_status`, scores).

| Stage | Written by | Notes |
|---|---|---|
| gateway | `semantic_cache.py` | whole request = end-to-end; `outcome` = cached / approved / rejected |
| cache_lookup | `semantic_cache.py` | `cache` = hit / miss, `similarity`, `miss_reason` (below_threshold, recall_guard, stale, empty_index) |
| facts_lookup | `semantic_cache.py` | MySQL record for the Writer / Reviewer (miss only) |
| queue_wait | each consumer | consumer receive time - Kafka CreateTime; `hop` = inbox, tasks, drafts, final |
| planner / writer / reviewer | the agents | model call + send; Writer span = error when the message goes to the dead letter |
| evaluation | `evaluator.py` | 3 judge calls; error on join timeout or judge failure |

A Reviewer rejection is recorded as `outcome = rejected`, not as an error: the request completed. Errors are exceptions and timeouts.

### 4.2 Trace examples (`raw/trace_examples.json`)

| Path | trace_id | Journey |
|---|---|---|
| Cache hit | `b21e9595-2f0e-4641-8fcf-4fa25fdd717e` | cache_lookup hit 205.8 ms → gateway 206.8 ms, no Kafka stage |
| Cache miss (approved) | `0aaa45c3-1488-43bc-a1d3-1a6ac35e20fe` | cache_lookup miss 157 ms → facts 677 → inbox 34 → planner 13,472 → tasks 195 → writer 9,208 → drafts 113 → reviewer 8,672 (approved) → final 77; gateway 32,897 ms; evaluation 68,756 ms |
| Failed | `fb34ab83-8eec-471a-b121-0835b7f2348c` | sent with `{"fail_at": "writer"}`: planner ok → **writer error** `RuntimeError: injected failure (fail_at=writer) -> dead letter after 3 attempts` → gateway error `TimeoutError` after 60 s → evaluation error `incomplete: no draft, final within 120s` |

Failing stage: **writer**. The gateway and the evaluator fail as a consequence.

### 4.3 Stage latency - 50 confirmed cache misses

Questions: `raw/latency_questions.json` (random.Random(9275)): 38 about real recall records whose number has no cache entry, 6 about recall numbers that do not exist, 6 off-domain. Each was pre-checked against the cache (0 replaced). During the run `CACHE_STORE=0`, so no answer was written to the cache. Verification from the spans: **50/50 cache_lookup spans = miss**, all 50 complete with 4 queue hops and an evaluation.
Requests were sent one at a time, each after the previous evaluation finished: on 8 GB the judge and the agents share the GPU.

| Stage | p50 (ms) | p95 (ms) | % of cache-miss end-to-end |
|---|---|---|---|
| Cache lookup | 343.9 | 1,222.5 | 2.0 |
| Facts lookup (MySQL) | 102.3 | 290.2 | 0.5 |
| Planner | **9,550.0** | 13,832.0 | **40.1** |
| Writer | 8,481.2 | 12,004.8 | 34.5 |
| Reviewer | 5,367.2 | 8,285.8 | 20.3 |
| Queue wait (total, 4 hops) | 107.0 | 715.0 | 2.6 |
| Gateway overhead | -20.3 | -6.3 | -0.2 |
| **End-to-end (cache miss)** | **23,135.2** | **35,508.3** | 100 |
| Evaluation (off the request path) | 44,775.9 | 58,208.8 | (188.2) |
| Cache hit end-to-end (separate, n = 10) | 145.5 | 194.3 | - |

Queue wait by hop, p50 / p95 ms: inbox 39.3 / 437.5 · tasks 32.7 / 163.9 · drafts 24.2 / 118.1 · final 11.4 / 67.8.
Percentages = sum of the stage over the 50 requests / sum of end-to-end. Gateway overhead = end-to-end - all stages; it is slightly negative because each hop's queue wait starts at the producer's CreateTime while the sending stage's span still includes the `flush()`, so a few ms are counted twice.

- **Dominant contributor: the Planner (40%)**; the three model stages together are 95%. Queues and the cache are under 5%.
- The Planner took 5.8 s in a single test with the judge idle, 9.6 s p50 here. It is the first model call after the judge ran, so Ollama swaps qwen3:4b out and qwen2.5:3b in on this 8 GB Mac; that load time lands in the Planner span.
- **Optimise first:** (1) take the judge off the agents' GPU (separate host, or batch evaluation outside serving hours) so no request pays a model swap; (2) replace the Planner model call with a rule-based plan for the fixed lookup questions ("units / firm / date / product / category of recall X"), which are almost all of the traffic - Part 2 shows the plans add little quality.
- A cache hit costs 145 ms p50 (embedding + Redis KNN) against 23.1 s for a miss: about 160x.
- Inbox p95 437 ms: the Planner was still inside its 1 s `poll()` when the next request arrived.

First attempt (not used): two evaluator processes were in the `s9275_evaluator` group at once (a test instance left running), so Kafka split the partitions and one instance never saw the plans (`incomplete ['plan']`); the gateway consumer was also dropped after 300 s without `poll()` (MAXPOLL). Fix: one process per group (checked with `kafka-consumer-groups --describe --members` before the run) and `max.poll.interval.ms` = 1 h for the gateway consumer. All data was deleted and the run repeated with new trace_ids.
