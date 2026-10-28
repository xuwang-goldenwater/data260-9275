# HW8 Metrics - Xu Wang (SID4 9275)

SID4 9275 · PORT_BASE 8275 · PREFIX s9275 · SEED 9275 · VERIFY_SEED 269275 · DOMAIN_ID 3 (Grocery supply and recall notices)
Hardware: MacBook Pro, Apple M1, 8 GB · Kafka: apache/kafka 3.8.0 (KRaft, 1 broker) in Docker · Model: qwen2.5:3b via Ollama (temperature 0, seed 9275)
All runs on 2026-10-27. Raw evidence: `raw/`.

## Part 1 - request/response over Kafka

Topics: `s9275_recall_notice_requests` (1 partition), `s9275_recall_notice_responses` (1 partition).

| Request | Path | Result | correlation_id echoed | Evidence |
|---|---|---|---|---|
| CREATE_RECALL_NOTICE | homework_demo.py -> Kafka -> worker | success, new UUID `08b73dc8-...` | yes | raw/part1_demo.log |
| GET_RECALL_NOTICE (that id) | homework_demo.py -> Kafka -> worker | success, same record returned | yes | raw/part1_demo.log |
| CREATE, no productName | FastAPI -> Kafka -> worker | `Missing field: productName` | yes (`err-missing-1`) | raw/part1_errors.log |
| CREATE, category "Spoiled" | FastAPI -> Kafka -> worker | `Invalid field: category ...` | yes (`err-category-1`) | raw/part1_errors.log |
| GET unknown id | FastAPI -> Kafka -> worker | `Recall notice not found` | yes (`err-notfound-1`) | raw/part1_errors.log |
| DELETE_RECALL_NOTICE | FastAPI -> Kafka -> worker | `Unknown operation` | yes (`err-op-1`) | raw/part1_errors.log |

Round trip client SENT -> client RECEIVED: CREATE 68 ms, GET 36 ms.

## Part 2 - three-agent pipeline

| Stage | Topic read | Topic written | Time in stage |
|---|---|---|---|
| client | - | s9275_inbox | - |
| Planner | s9275_inbox | s9275_tasks | 4.1 s |
| Writer (w1) | s9275_tasks (partition 0) | s9275_drafts | 9.2 s |
| Reviewer | s9275_drafts | s9275_final | 3.2 s |
| end to end | | | 16.5 s |

Final message: `status: approved`, 85-word answer, `trace` = planner -> writer-w1 -> reviewer, correlation_id unchanged (raw/part2_journey.log, raw/part2_final.json).

Found while testing: the first Writer prompt made qwen2.5:3b copy the plan as its answer, and the model Reviewer approved it. Fix: rewritten Writer prompt + deterministic Reviewer rule (draft vs plan similarity >= 0.8 -> rejected). The copied draft scores 1.00.

## Part 3 - failure table

| Failure scenario | Before fix | After fix |
|---|---|---|
| Duplicate delivery (same task, same correlation_id, sent twice) | `FIX_IDEMPOTENCY=0`: both copies processed, 2 model calls, **2 drafts** in s9275_drafts for `dup-0c594693` | correlation_id already in the processed store -> `DUPLICATE ... skipped`, **1 draft** for `dup-9bd1743b` |
| Consumer killed mid-work (`kill -9` during 20 s of work) | `FIX_MANUAL_COMMIT=0` (auto-commit 1 s): offset committed before work finished (partition 0 LAG 0); restarted Writer got nothing; **0 drafts** for `kill-a0c7ae0b` - message lost | offset committed only after the draft is sent: LAG 1 after the crash; restarted Writer re-read **the same offset 5**, finished, committed 6; **1 draft** for `kill-e2ca57a0` |
| Poison message (task with no `question`, normal task behind it) | `FIX_DLQ=0`: KeyError kills the Writer; restart re-reads the same offset 7 and dies again; partition 1 LAG 2 - the normal task is blocked | 3 attempts (0.5 s, 1 s backoff) -> `s9275_dead_letter` with error + original -> commit 8 -> normal task `after-poison-542fb13e` processed, **1 draft** |
| Two partitions / two consumers (20 related tasks, VERIFY_SEED 269275, 4 recalls x 5 steps) | no key, spread over both partitions: every recall split over partitions 0,1 and Writers w1,w2; **3 order violations** (`RN-c6810e` 1,2,4,3,5 · `RN-c973f5` 1,3,2,5,4) | key = recall_notice_id: each recall in one partition, one Writer; all four `[1,2,3,4,5]`; **0 violations** |

### Ordering runs in detail

| Run | recall | partitions | writers | seq in processing order | violations |
|---|---|---|---|---|---|
| nokey | RN-c6810e | 0,1 | w1,w2 | 1, 2, 4, 3, 5 | 1 |
| nokey | RN-c973f5 | 0,1 | w1,w2 | 1, 3, 2, 5, 4 | 2 |
| nokey | RN-c97b16 | 0,1 | w1,w2 | 1, 2, 3, 4, 5 | 0 |
| nokey | RN-efb54f | 0,1 | w1,w2 | 1, 2, 3, 4, 5 | 0 |
| keyed | RN-c6810e | 0 | w2 | 1, 2, 3, 4, 5 | 0 |
| keyed | RN-c973f5 | 1 | w1 | 1, 2, 3, 4, 5 | 0 |
| keyed | RN-c97b16 | 1 | w1 | 1, 2, 3, 4, 5 | 0 |
| keyed | RN-efb54f | 0 | w2 | 1, 2, 3, 4, 5 | 0 |

A violation = a step processed after a higher-numbered step of the same recall.
Ordering runs replace the model call with 0.1-0.6 s of fixed work per (recall, step), so the only
difference between the two runs is the message key. The no-key run assigns partitions round-robin
(`i % 2`), because librdkafka's sticky partitioner would otherwise put a fast burst of 20 keyless
messages into one partition and hide the problem.
