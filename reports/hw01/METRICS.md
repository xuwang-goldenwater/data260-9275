# METRICS.md — Homework 1, Part 3

## Experiment setup

| Item | Value |
|---|---|
| Frozen input | `reports/hw01/cases/nondeterminism_input.json` (89-word recall notice) |
| Pipeline | `code/agents_demo.py` — Planner → Reviewer → Finalizer |
| Model | `qwen3:8b` via Ollama |
| Hardware | MacBook Pro, 8 GB RAM |
| Runs | 20 at temperature 0.7, 20 at temperature 0.0 |
| Run date | 2026-08-30, 21:51–22:01 PDT |
| Raw data | `reports/hw01/raw/nondeterminism_runs.{jsonl,csv}` |
| Console log | `reports/hw01/RUN_LOG.txt` |

Tag sets are compared without regard to order, so a reordering of the same
three tags counts as one set rather than two.

## Results

| Metric | Temp 0.7 | Temp 0.0 |
|---|---|---|
| Distinct tag sets | 2 | 1 |
| Tags in all 20 runs | 2 | 3 |
| Tags in exactly 1 run | 0 | 0 |
| Latency p50 / p95 / p99 (ms) | 12,122 / 15,876 / 18,586 | 12,378 / 30,359 / 36,294 |

Additional measures collected in the same runs:

| Metric | Temp 0.7 | Temp 0.0 |
|---|---|---|
| Distinct summaries | 9 | 1 |
| Runs where the Reviewer changed the Planner's output | 17 / 20 | 20 / 20 |
| Distinct tags seen overall | 4 | 3 |

### Tag frequency

**Temperature 0.7**

| Tag | Runs (of 20) |
|---|---|
| peanut butter | 20 |
| product recall | 20 |
| milk contamination | 18 |
| milk allergy | 2 |

**Temperature 0.0**

| Tag | Runs (of 20) |
|---|---|
| peanut butter | 20 |
| milk contamination | 20 |
| product recall | 20 |

## Observations

**1. Temperature 0.0 produced no variation at all in these runs.**
One tag set and one summary across 20 runs. This does not prove the pipeline is
deterministic in general — floating-point accumulation order on the GPU and
server-side batching can still introduce differences, and 20 runs on one input
is a small sample. It shows only that no variation surfaced under these
conditions.

**2. Tags were far more stable than summaries.**
At temperature 0.7 there were only 2 distinct tag sets but 9 distinct
summaries. The tag field is short, constrained to three items, and drawn from
words in the source text; the summary is free-form prose with many valid
phrasings. Constraining the shape of an output is what makes it reproducible,
not lowering the temperature alone.

**3. The single tag that varied is the safety-relevant one.**
Two of the three tags were identical in all 40 runs. The one that moved was the
hazard tag: `milk contamination` in 18 runs, `milk allergy` in 2. Both describe
the same underlying hazard, but they are different strings, and any downstream
system that routes on the tag would treat them as different categories.

**4. Temperature did not change per-run cost; machine state did.**
The p50 latencies are within 2% of each other (12.1 s vs 12.4 s), which is
expected — sampling temperature does not change how many tokens are generated
or how fast each one is produced. The much heavier tail at temperature 0.0
(p95 30.4 s vs 15.9 s) is not a temperature effect. In `RUN_LOG.txt` the slow
runs are a contiguous block, runs 10 through 15, at 20–36 s while every run
before and after is 10–13 s. That pattern is consistent with memory pressure on
an 8 GB machine, not with sampling behaviour. Reading the tail difference as
"temperature 0.0 is slower" would be a misreading of this data.

**5. The Reviewer agent does real work.**
It altered the Planner's output in 37 of 40 runs, almost always replacing
`milk allergy` with `milk contamination` and giving the reason "more specific
and better reflects the content". The three runs where it made no change are
the runs where the Planner had already produced the tag the Reviewer preferred.

## Required analysis

### What two users sending identical input might see

At temperature 0.7, two users submitting this same recall notice would receive
the same three tags about 90% of the time (18 of 20 runs) and different tags
about 10% of the time: one user sees `milk contamination`, the other sees
`milk allergy`. The summaries differ far more often — 9 distinct wordings in 20
runs — so two users are more likely than not to read differently-phrased
summaries of the same facts. At temperature 0.0 both users saw identical output
in every run.

### One case where run-to-run variation is acceptable

**Summary wording shown to a human reader.** All 9 distinct summaries carried
the same facts: the product, the undeclared milk, the allergy risk, and the
recall. A person reading any one of them learns the same thing and takes the
same action. The same applies to using tags as search facets or to surface
"related notices" — a user who sees `milk allergy` instead of `milk
contamination` still finds relevant material. Nobody is harmed by the
difference.

### One case where it is not acceptable

**Routing allergen alerts by tag.** If the tag drives which subscribers are
notified — for example, everyone who has registered a milk allergy — then the
10% of runs producing `milk allergy` instead of `milk contamination` reach a
different audience. Under the FDA classification, a Class I recall is one with
a reasonable probability of serious adverse health consequences or death, and
undeclared milk in a peanut butter product is exactly that case. A one-in-ten
chance of routing a life-safety alert to the wrong list is a defect, not
tolerable variance.

The fix is not simply to set temperature to 0. It is to take the
safety-critical field out of free generation entirely: the submission form in
Part 1 makes the user choose `category` from four fixed values rather than
letting a model produce that string. Free-text tags remain useful for search
and discovery, where the variation measured above does no harm.
