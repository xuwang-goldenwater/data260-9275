# HW6 METRICS — Xu Wang (SID4 9275)

Model `qwen2.5:3b` via Ollama (temperature 0, seed 9275, num_ctx 8192) on a MacBook Pro M1, 8 GB.
Embeddings: `all-MiniLM-L6-v2` on CPU. Token counts per section: Qwen2.5 tokenizer.

## Part 3 — What memory costs

**Setup.** The fixed 30-message conversation (`conversation_30.yaml`) was replayed in a fresh
user and session for each setting, then the five probes in `memory_probes.yaml` were asked.
Both files were committed (3423420) before any run; the runs used code commit 6a7157c.
Raw data: `raw/part3_turns.jsonl` (140 turns), `raw/part3_probe_scores.csv` (hand-scored),
`raw/part3_summary.json`. Means are over the 30 conversation turns; probe turns are excluded.

| Setting | Mean prompt tokens/turn | Mean latency (ms) | Probe quality (1-5) |
|---|---|---|---|
| SHORT_TERM_N=4 | 378.4 | 9088 | 4.6 |
| SHORT_TERM_N=12 | 702.6 | 13982 | 5.0 |
| SHORT_TERM_N=30 | 1166.2 | 17089 | 4.8 |
| Compression policy (N=30, assistant replies cut to first sentence) | 687.5 | 9595 | 5.0 |

Latency is the whole turn: retrieval + chat call + fact extraction + any summary update.

**Where the prompt tokens go** (mean per turn):

| Setting | System primer | Long-term summary | Short-term window | Current message | Episodic facts | Chat template |
|---|---|---|---|---|---|---|
| N=4 | 83 | 101.8 | 121.0 | 9.9 | 38.2 | 24.5 |
| N=12 | 83 | 106.9 | 419.9 | 9.9 | 38.2 | 44.7 |
| N=30 | 83 | 101.8 | 854.4 | 9.9 | 38.2 | 78.9 |
| Compression | 83 | 102.5 | 375.1 | 9.9 | 38.2 | 78.9 |

**Probe scores** (rubric in `memory_probes.yaml`):

| Setting | P1 allergy | P2 store now | P3 son | P4 trip | P5 product |
|---|---|---|---|---|---|
| N=4 | 5 | 5 | 5 | 3 (date only, no Yosemite) | 5 |
| N=12 | 5 | 5 | 5 | 5 | 5 |
| N=30 | 4 (Mia, not called the daughter) | 5 | 5 | 5 | 5 |
| Compression | 5 | 5 | 5 | 5 | 5 |

### Eviction / compression comparison

| | N=30 (full) | N=30 compressed | Change |
|---|---|---|---|
| Mean prompt tokens/turn | 1166.2 | 687.5 | −41.0% |
| Short-term window tokens/turn | 854.4 | 375.1 | −56.1% |
| Mean completion tokens/turn | 56.6 | 30.5 | −46.1% |
| Mean latency (ms) | 17089 | 9595 | −43.9% |
| Probe quality | 4.8 | 5.0 | +0.2 |

Policy `compress_assistant`: the window keeps the last 30 messages, user messages verbatim and
each assistant reply cut to its first sentence (≤160 characters). Facts about the user are in
the user's own messages; the assistant replies were most of the window.

### Cost estimate — 10,000 conversations × 30 turns ($1/M input, $5/M output)

| Setting | Chat tokens per conversation (in / out) | Chat calls only | Chat + memory upkeep* |
|---|---|---|---|
| N=4 | 11,353 / 1,504 | $188.73 | $278.21 |
| N=12 | 21,078 / 1,876 | $304.58 | $395.26 |
| N=30 | 34,987 / 1,699 | $434.82 | **$524.30 (worst)** |
| Compression | 20,626 / 915 | $252.01 | **$341.60 (best)** |

\* Upkeep = the extra model calls memory causes: fact extraction on every user message and a
summary update every 4th one (≈4,660 input + 860 output tokens per conversation, about $90 per
10,000 conversations, the same in every setting).

**How best and worst were chosen.** Best = the cheapest setting that scored 5.0 on the probes:
the compression policy ($341.60). Worst = SHORT_TERM_N=30: the most expensive setting
($524.30, 1.5× the best) and still not the top probe score. N=4 is cheaper ($278.21) but lost a
point on P4 (the trip location), so it was not chosen as best.

### Observations

- The short-term window drives the cost: 73% of the N=30 prompt. The long-term summary and the
  episodic facts together cost about 140 tokens per turn in every setting.
- Probe quality hardly depends on N. Facts from messages 1–14 are outside every window when
  the probes are asked (N=30 only reaches back to message 16), so P1–P4 were answered from the
  summary and episodic facts in all four settings.
- Message 20 ("keep your answers under 50 words") made later replies shorter, so the N=12 and
  N=30 windows shrank after turn 20 (N=30: 1439 → 566 window tokens). A user preference
  changed the cost of memory.
- Compression also halved the reply length, probably because the model copies the
  one-sentence replies it sees in the window. Output tokens cost 5× input, so this side effect
  added to the saving. The probes check recall only, not whether shorter answers are still
  helpful.
- Memory upkeep is a large share for small windows: about 32% of the N=4 total.

### Limitations

One run per setting, five probes, and a ceiling effect (17 of 20 answers scored 5). Differences
of 0.2–0.4 points are within run-to-run noise. Probes were scored by one person (Xu Wang).

## Part 4 — File-based memory and consolidation

### 4-5 Consolidation of the 55-line MEMORY.md

Input `memory/MEMORY.original.md`: 55 lines (53 counted: non-empty, non-comment), 51 facts —
18 unique facts, 6 duplicate groups (23 lines), 4 contradictions (8 lines) and 1 trap
(2 lines: a home city and a temporary trip). The answer key `memory/memory_55_key.yaml` was
committed before the run. Result `memory/MEMORY.consolidated.md`; grading
`memory/consolidation_eval.json` (`make memory-consolidate`).

| | Before | After |
|---|---|---|
| Counted lines | 53 | **39** (< 40) |
| Facts | 51 | 34 |
| Silently deleted facts | — | 0 |

| Item | Expected | Result |
|---|---|---|
| D1 daughter Mia, tree nuts (4 lines) | merge | merged |
| D2 short bullet answers (4) | merge | merged |
| D3 repository name (4) | merge | merged |
| D4 port 8275 (4) | merge | partly (3 of 4) |
| D5 conda env data260 (4) | merge | partly (2 of 4) |
| D6 name in screenshots (3) | merge | merged, **but also swallowed "User's name is Xu Wang."** (false merge) |
| C5 HW6 deadline | Oct 22 replaces Oct 20 | correct |
| C1 Safeway → Costco | Costco replaces Safeway | **missed** (both kept, unresolved) |
| C2 qwen3:8b → qwen2.5:3b | newer model wins | **missed** |
| C3 Google Docs → Word | Word wins | **missed** |
| C4 trap: lives in San Jose / in Los Angeles this week | keep both | **resolved incorrectly**: "in Los Angeles this week" superseded "lives in San Jose" |

**Contradictions resolved incorrectly:** C4 (newest-date-wins cannot tell a temporary state from
a permanent fact), plus C1–C3 left unresolved. Resolved items are written explicitly under
"## Resolved contradictions" with both facts and their dates, so nothing is deleted silently.

How it works: MiniLM pairs similar facts (cosine ≥ 0.45), qwen2.5:3b labels each pair
duplicate / contradiction / different, and the code applies the rules (a duplicate group keeps
its newest wording; in a contradiction the newer date wins). A first version that gave the
model all 51 lines in one prompt returned an empty plan (14 output tokens) and changed nothing.

### 4-4 One function checked against AGENT.md

`code/doc_app/recall_number.py: parse_recall_number()` with `code/doc_app/test_recall_number.py`.

| AGENT.md rule (category) | Followed? | Where |
|---|---|---|
| Type hints on every parameter and return value (coding conventions) | ✅ | `(value: str) -> Tuple[int, int]` |
| Docstring says what it returns and when it fails (coding conventions) | ✅ | docstring |
| Config values not hardcoded (coding conventions) | ✅ | uses `config.RECALL_NUMBER_PATTERN` |
| Invalid input raises `ValueError` naming the value; no `print()` (coding conventions) | ✅ | two `raise ValueError(... {value!r} ...)` |
| Offline test with a valid and an invalid case (testing approach) | ✅ | `test_valid`, `test_invalid` |
| No hardcoded ports, paths or credentials (prohibited actions) | ✅ | none in the file |

### 4-6 MongoDB memory vs. file-based memory

| | MongoDB (Part 2) | Files: AGENT.md + MEMORY.md (Part 4) |
|---|---|---|
| Inspectability | Needs Compass or queries; embeddings are 384 numbers. The Part 2 memory poisoning was only found by querying. | Plain text anyone can read; `git diff` shows every change (original vs consolidated). |
| Persistence after restart | Kept in the Docker volume `s9275_mongo_data`. | Kept on disk, plus git history to roll back. |
| Scalability across sessions | Indexed by user and session; four Part 3 users and hundreds of messages did not interfere. | One file, sent whole in every prompt; 55 lines already needed consolidation; concurrent writes would clash. |
| Facts that must not be forgotten | Episodic recall is by similarity and not guaranteed ("allergy" scored cosine 0.097 for "Which recalls should I worry about?"). | Every line is in every prompt, so nothing depends on retrieval — but automatic consolidation can still drop a fact (trap C4), so critical facts belong in AGENT.md or must be protected from consolidation. |

Use both: durable rules and must-keep facts in files, the large conversation history in the
database with retrieval.
