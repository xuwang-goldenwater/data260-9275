# HW5 Metrics

SID4 9275 | PREFIX s9275 | SEED 9275 | VERIFY_SEED 269275 | PORT_BASE 8275 | DOMAIN_ID 3 (grocery supply and recall notices)

## Part 3 - Tool contracts under stress

Source: `make fault-injection`, run of 2026-10-05 07:30:16 on MySQL `s9275_rel`.
Raw data: `raw/fault_injection_calls.csv` (150 rows, one per call) and
`raw/fault_injection_summary.json`. Console output: `RUN_LOG.txt`.

### Retry policy under test

| Setting | Value |
|---|---|
| Attempts per storage operation | 3 (first try + 2 retries) |
| Timeout per attempt | 2.0 s |
| Wait before retry 1, retry 2 | 0.1 s, 0.2 s (doubles each time) |
| Cap on any single wait | 1.0 s |
| Retried | injected failures, timeouts, lost connections |
| Not retried | invalid inputs, "not found", programming errors |

### Results (step 20)

50 calls per rate, the same 50 calls each time (the three tools in turn, valid
inputs). Failures are injected before each storage attempt from
`random.Random(269275)`.

| Injected failure rate | Success rate | Mean latency (ms) | p99 latency (ms) |
|---|---|---|---|
| 0% | 100.0% (50/50) | 2.41 | 13.99 |
| 20% | 100.0% (50/50) | 27.91 | 326.33 |
| 50% | 88.0% (44/50) | 105.72 | 329.20 |

p99 is the nearest-rank percentile. With 50 values per rate it is the largest
value, so it shows the worst call of each group.

Supporting numbers from the same run:

| Injected failure rate | Storage attempts | Injected failures | Succeeded on attempt 1 / 2 / 3 | Failed after 3 attempts |
|---|---|---|---|---|
| 0% | 50 | 0 | 50 / 0 / 0 | 0 |
| 20% | 59 | 9 | 43 / 5 / 2 | 0 |
| 50% | 86 | 42 | 26 / 12 / 6 | 6 |

Mean latency by outcome (20% and 50% groups): first attempt 5-7 ms, second
attempt 106-114 ms, third attempt 316-325 ms, failed after three attempts 308 ms.

### Reproducibility

Per call, `1`/`2`/`3` = succeeded on that attempt, `X` = failed after every allowed attempt:

```
  0%  11111111111111111111111111111111111111111111111111
 20%  11111111112111111111121322111111111311111111121111
 50%  22111122211212313X21X1XX1111121311132321X1X1123111
```

Each line equals what the seed alone predicts (`expected_attempts()` in
`code/fault_injection.py` computes it without touching the database), and the
SHA-256 signature of the 150 (rate, call, attempts, ok) records starts with
`6c4b498b7aab90a0` on every run. Latency changes between runs; the
success/failure sequence does not.

### Is the policy suitable for an interactive assistant? (step 21)

Yes for failures that return quickly, with one setting to tighten.

- **The wait is bounded and short.** The backoff adds at most 0.1 + 0.2 = 0.3 s.
  The slowest call in the whole experiment took 329 ms. A turn of the local
  model takes seconds, so the user does not notice a retry.
- **Retries hide moderate trouble completely.** At 20% injected failures all 50
  calls succeeded: 9 failures were absorbed by 9 extra attempts. The price was
  the mean rising from 2.4 ms to 27.9 ms.
- **Under heavy trouble it fails fast and cleanly.** At 50%, 6 of 50 calls (12%)
  failed, which is what three independent attempts predict (0.5^3 = 12.5%).
  Each of those came back in about 0.3 s as `{"ok": false, "data": null,
  "error": "..."}`. For a conversation that is better than waiting longer: the
  assistant can say the data is unavailable, or the agent can try something else.
- **What I would change: the timeout.** Injected failures fail instantly, so
  this experiment does not show the cost of a storage call that hangs. With a
  2 s timeout the worst case is 3 x 2 s + 0.3 s = 6.3 s. Normal queries here
  take 1-14 ms, so for interactive use I would lower the timeout to about 1 s
  (worst case 3.3 s) and keep 3 attempts.

More attempts would raise the 50% success rate (5 attempts: 96.9%) but the
waits would become 0.1 + 0.2 + 0.4 + 0.8 = 1.5 s, which is too slow for a chat
turn. I would not add attempts for interactive use.

### How I would change it for batch processing

In a batch job nobody is waiting for one answer, so the goal changes from
"answer quickly or say no" to "finish every item".

| Setting | Interactive (as tested) | Batch |
|---|---|---|
| Attempts | 3 | 6-8 |
| Timeout per attempt | 2 s (1 s preferred) | 30 s |
| First wait / multiplier | 0.1 s / x2 | 1 s / x2 |
| Cap on a single wait | 1 s | 30-60 s |
| Jitter | none | random +/- 50% on every wait |
| When retries run out | return ok:false at once | record the item and re-run it at the end |

- **More attempts.** With a 50% failure rate, 6 attempts succeed 98.4% of the
  time and 8 attempts 99.6% (1 - 0.5^n), against 87.5% for 3.
- **Longer waits and a higher cap.** A database that is restarting or
  overloaded needs seconds to minutes, not 0.3 s. Waits of 1, 2, 4, 8, 16, 30 s
  give it that time.
- **Jitter.** Many batch workers that fail together would otherwise retry at the
  same instants and hit the database in waves. A random factor spreads them
  out. It is left out of the tested policy so that the latency in this
  experiment stays explainable.
- **Longer timeout.** A heavy aggregate query can legitimately take many
  seconds in a batch; 2 s would cut off work that is about to succeed.
- **Keep it bounded anyway.** Attempts and waits still have limits, and an item
  that exhausts them goes to a list for a later pass instead of stopping the
  whole job. All three tools only read, so running an item again is safe.

## Part 5 - Agent harness

Source: `make agent-scenarios`, run of 2026-10-05 08:30-08:39, local model
`qwen3:8b` through Ollama (temperature 0), tools reading MySQL `s9275_rel`.
Raw data: `raw/agent_scenarios.json` (the table below) and
`raw/agent_runs.jsonl` (one line per run with every model step, tool call and
tool result; find a run by its `run_id`). Console output: `RUN_LOG.txt`.

### How the loop counts and stops

One step = one call to the model, plus running every tool it asked for.
`run_agent()` stops for one of these reasons:

| Stop reason | Meaning |
|---|---|
| `completed` | the model answered in text and asked for no tool |
| `safety_block` | `execute_tool` refused a call under the safety rule; the loop ends at once |
| `max_steps` | the step budget ran out before the model gave a final answer |
| `model_error` | the model call itself failed (not seen in these runs) |

Default budget: `MAX_STEPS = 5`.

### Results

| Scenario | What it tests | max_steps | Steps | Tool calls | Stop reason | Tools called | Seconds | run_id |
|---|---|---|---|---|---|---|---|---|
| S1 | one aggregate call, then an answer | 5 | 2 | 1 | `completed` | recall_summary | 197.9 | 75f5e739 |
| S2 | two tools in sequence: search, then detail lookup | 5 | 3 | 2 | `completed` | search_notices, get_notice | 134.4 | 52422676 |
| S3 | a request the safety rule refuses | 5 | 1 | 1 | `safety_block` | recall_summary | 24.9 | d680adb7 |
| S4 | the S2 question with a budget of 2 steps | 2 | 2 | 2 | `max_steps` | search_notices, get_notice | 124.0 | 5ffba3f4 |
| S5 | an invalid tool input (recall number in the wrong format) | 5 | 2 | 1 | `completed` | get_notice | 82.4 | 228f75ce |

Questions:

- S1: "How many recall notices were there in 2025, broken down by category?"
- S2 and S4: "Find the most recent peanut butter recall and tell me which firm issued it and that firm's contact email."
- S3: "Which firms have the most recall notices? List the top 10."
- S5: "Give me the details of recall number 4906."

### What happened in each run

- **S1.** `recall_summary(group_by=category, year=2025)` returned 867 notices in
  4 categories. The answer repeats the tool's numbers exactly (347 / 231 / 145 / 144).
- **S2.** `search_notices("peanut butter", limit=1)` found `F-4906-2026`, then
  `get_notice("F-4906-2026")` returned the firm and its email. The answer
  (Meadow Bakery Inc., recalls@firm167.example.com) matches the tool result.
- **S3.** The first call was `recall_summary(group_by=firm)`. The safety rule
  refused it before any query ran, and the loop stopped after 1 step.
- **S4.** The same two calls as S2. Both steps were used for tool calls, so the
  loop stopped with `max_steps` before the model could write the answer, even
  though the data had already been fetched. A question that needs N tool calls
  needs N + 1 steps.
- **S5.** `get_notice("4906")` failed input validation (`ok: false`, pattern
  `^F-\d{4}-\d{4}$`). This is not a safety block, so the error went back to the
  model, which explained the required format in step 2. The stop reason is
  `completed` although the user did not get the notice: `completed` means the
  loop ended normally, not that the question was answered.

### Before and after changing the tool descriptions

The first batch (08:19-08:22, kept in `raw/agent_scenarios_run1.json`) gave a
different result for the peanut butter question:

| Scenario | Batch 1 stop reason | Batch 1 tools called | Batch 2 stop reason | Batch 2 tools called |
|---|---|---|---|---|
| S1 | `completed` (2 steps) | recall_summary | `completed` (2 steps) | recall_summary |
| S2 | `safety_block` (2 steps) | search_notices, recall_summary | `completed` (3 steps) | search_notices, get_notice |
| S3 | `safety_block` (1 step) | recall_summary | `safety_block` (1 step) | recall_summary |
| S4 | `safety_block` (2 steps) | search_notices, recall_summary | `max_steps` (2 steps) | search_notices, get_notice |
| S5 | `completed` (2 steps) | get_notice | `completed` (2 steps) | get_notice |

In batch 1, after the search the model called
`recall_summary(group_by=firm, year=2026)` to find the firm's email. The safety
rule blocked it, so a harmless question was refused (run_id `3adaf676`).

Between the batches I changed only the text the model reads: the three tool
descriptions in `code/domain_tools.py` and the system prompt in
`code/agent_loop.py` now say that `get_notice` returns the firm and its contact
email and that `recall_summary` is for statistics only. The safety rule and the
loop are unchanged. The longer text costs 137 input tokens per model call
(S1 step 1: 556 -> 693).

Limits of this comparison: one run per scenario per batch, temperature 0, one
wording of each question. It shows the change fixed this question, not that the
model will always pick the right tool.

### Timing

Model steps took 7-54 s in batch 1 and 21-129 s in batch 2 for the same calls
(S1: 108.5 s, then 197.9 s). `ollama ps` shows the 6.0 GB model split 24% CPU /
76% GPU on this machine, so it does not run fully on the GPU. Seconds are not
comparable between batches; steps, tool calls and stop reasons are.

### Other runs in the log

`raw/agent_runs.jsonl` holds 14 runs: 4 single trials made while building the
loop (one of them with `qwen3:4b`, which was not faster and printed its
reasoning into the answer, so `qwen3:8b` was kept), then the 5 runs of batch 1
and the 5 runs of batch 2.

The three stop reasons are also checked without Ollama or MySQL by tests 16-18
in `code/test_tools.py` (`make test-tools`), using `MockModel` and the
in-memory repo.
