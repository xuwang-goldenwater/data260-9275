# METRICS.md — Homework 2, Part 4

## Experiment setup

| Item | Value |
|---|---|
| Frozen input | `reports/hw02/cases/schema_input.json` (89-word recall notice, saved before the runs) |
| Adversarial input | `reports/hw02/cases/adversarial_input.json` |
| System under test | `code/agent_graph.py` — Supervisor / Planner / Reviewer LangGraph |
| Model | `qwen3:8b` via Ollama, temperature 0.0, through `src/model_client.py` |
| Hardware | MacBook Pro, 8 GB RAM |
| Output contract | exactly 3 tags, each 3–30 characters; summary ≤ 25 words |
| Runs | 30 + 20 + 20 + 5 = 75 |
| Run window | 2026-09-11, 12:06–12:33 PDT |
| Model calls | 190 total, 78,294 input tokens, 7,579 output tokens |
| Raw data | `raw/graph_runs.{jsonl,csv}`, aggregates in `raw/hw02_metrics.json` |
| Console log | `RUN_LOG.txt` |

One **turn** is one dispatch to an agent. A run that is right first time costs
two turns: Planner once, Reviewer once.

## Part 4.3 — 30 runs on the frozen input (ceiling 10)

| Outcome over 30 runs | Count | Mean latency (ms) |
|---|---|---|
| Valid first attempt | 30 | 17,594 |
| Valid after 1 retry | 0 | — |
| Valid after 2+ retries | 0 | — |
| Hit turn ceiling | 0 | — |

Latency p50 15,224 ms, p95 33,030 ms, min 9,027 ms, max 53,767 ms.

**The retry path never fired.** On a well-formed recall notice the Planner
produced a schema-valid proposal on the first attempt in all 30 runs, and the
Reviewer accepted it in all 30. Every run cost exactly 2 turns and 2 model
calls. The measured headroom was large rather than marginal: summaries came in
at 17–18 words against a 25-word limit, and tags at 12–14 characters against a
30-character limit.

This is a real result, not a missing one, and it sets up Part 4.4: a ceiling
cannot be evaluated on input that never needs it.

## Part 4.4 — turn ceiling 2 vs 10

Same frozen input, same model, same temperature, 20 runs each.

| Metric | Ceiling 2 | Ceiling 10 |
|---|---|---|
| Completion rate | 100% (20/20) | 100% (20/20) |
| Mean latency (ms) | 13,941 | 19,168 |
| Median latency (ms) | 11,163 | 14,618 |
| p95 latency (ms) | 19,343 | 35,838 |
| Mean turns used | 2.0 | 2.0 |
| Mean planner attempts | 1.0 | 1.0 |
| Mean model calls | 2.0 | 2.0 |
| Input / output tokens | 12,760 / 1,300 | 12,760 / 1,300 |

**The latency difference is not caused by the ceiling.** Both arms executed
exactly 2 turns and 2 model calls per run and consumed byte-identical token
counts — 12,760 in and 1,300 out on both sides. A ceiling only binds when a run
tries to exceed it, and no run did. The 5.2-second gap in means is machine
noise on an 8 GB laptop, the same effect recorded in Homework 1, where a
contiguous block of runs slowed from 12 s to 20–36 s under memory pressure with
no change in the work being done. Reporting this gap as "ceiling 2 is faster"
would be a misreading of the data.

### Which one to deploy

**Ceiling 2**, on this data.

- On well-formed input the two are indistinguishable: identical completion
  rate, identical turns, identical token cost.
- They differ only on input that fails, and there the difference is the cost of
  failing. The adversarial case below took 11 turns, 10 model calls and 95
  seconds under ceiling 10 to arrive at the same outcome ceiling 2 reaches in
  3 turns and 2 model calls. Measured directly on the same input, ceiling 2
  abandoned it in 38.1 s with a warm model; the first run of the session, loading
  the model cold, took 67.5 s.
- So the choice is not between succeeding and failing. It is between failing
  fast and failing slow, and a fivefold increase in model calls on every
  pathological input buys nothing that this data can show.

The honest limit on that recommendation: with a first-attempt rate of 100% on
30 runs, this experiment never observed a run that *would* have been rescued by
a retry. It shows that retries are not needed here, not that they are never
needed. A ceiling of 2 permits exactly one Planner attempt plus one review; if
a later domain input turns out to need one correction, ceiling 2 would discard
work that ceiling 3 or 4 would save. The measurement to repeat before
generalising is Part 4.3 on a wider set of inputs.

## Part 4.5 — adversarial input

| Outcome over 5 runs | Count |
|---|---|
| Valid first attempt | 0 |
| Valid after 1 retry | 0 |
| Valid after 2+ retries | 0 |
| Hit turn ceiling | 5 |

Mean 11 turns, 10 model calls, 95,057 ms per run (p50 90,010 ms).

The adversarial notice is a real recall notice in shape. What makes it hostile
is that its salient product terms are long hyphenated compounds
(`Hydrolyzed-Vegetable-Protein-Seasoning-Blend`, 44 characters) and it carries
three separate hazards, two firms, four lot ranges and six states.

### Why it causes trouble

Not randomness. **All five runs produced an identical trace**, which is what
made the cause findable. Run 1, abbreviated:

| Step | What happened |
|---|---|
| P1 | tags `[hydrolyzedvegetableprotein, listeriamonocytogenes, stainlesssteelwire]` — **valid** |
| R1 | "`stainlesssteelwire` is not specific enough, should be `stainlesssteelwirefragments`" |
| P2 | complies — **valid** |
| R2 | "`hydrolyzedvegetableprotein` is not specific enough" |
| P3 | lengthens to `hydrolyzedvegetableproteinseasoning`, 35 chars — **rejected by the validator** |
| P4 | backs off to 26 chars — **valid** |
| R3 | "should be `hydrolyzed-vegetable-protein-seasoning-blend`" — that string is 44 chars |
| P5 | complies — **rejected by the validator** |
| P6 | backs off again — **valid** |
| R4 | "`product-recall` is too generic" … and so on until turn 11 |

The Planner is not failing. It produced a schema-valid proposal on 4 of its 6
attempts. The run never ends because **the Reviewer keeps demanding a tag the
validator forbids**. The Reviewer's system prompt asks for tags that are
"specific rather than generic" and says nothing about the 3–30 character limit,
so for a product whose specific name is 44 characters the two requirements are
in direct contradiction. No output satisfies both. This is a livelock: work is
being done on every step and no step moves the run closer to finishing.

The turn ceiling is the only thing that stops it. Without it, this input loops
forever on an input a human would call unremarkable.

### One fix

**Give the Reviewer the same output contract the validator enforces.**
`REVIEWER_SYSTEM` should state the 3–30 character tag limit and the 25-word
summary limit, and instruct the Reviewer to reject a proposal only for a
problem that can be fixed *within* those limits. The contradiction then cannot
be expressed: a Reviewer that knows about the 30-character cap cannot ask for a
44-character tag.

This is one prompt change, and it addresses the cause rather than the symptom.
Raising the ceiling would only make the loop longer; lowering it would hide the
loop without explaining it. A second, stronger version of the same fix is to
validate the Reviewer's *suggestion* against `PlannerOutput` before it is fed
back, so a suggestion that could not pass never reaches the Planner — the same
principle as Homework 1's deterministic Finalizer: put the hard contract in
code, not in a prompt.

## Observations

**1. Refactoring the Reviewer changed the published output.**
Identical input, identical model, identical temperature — but Homework 1
published `[peanut butter, milk contamination, product recall]` and Homework 2
publishes `[peanut butter, milk allergy, product recall]` in all 70
frozen-input runs. Nothing about the model changed. In HW1 the Reviewer
returned corrected tags and rewrote `milk allergy` to `milk contamination` in
37 of 40 runs. In HW2 the Reviewer only judges — it returns `has_issues` and a
sentence, and it reported no issue in 70 of 70 runs — so the Planner's original
wording survives to publication.

This matters because of what that tag is. HW1's own analysis singled out this
exact field as the safety-relevant one: if the tag routes allergen alerts to
subscribers, `milk allergy` and `milk contamination` reach different lists. An
architectural refactor that was meant to be about control flow silently moved a
safety-critical value.

**2. Temperature 0.0 is still not a determinism guarantee.**
Of 70 frozen-input runs, 69 produced one summary and run 1 of `schema30`
produced a different one — the first run of the session, on a cold model.
Tag sets were identical in all 70. This matches Homework 1's finding at a
larger sample: constraining the *shape* of an output is what makes it
reproducible, and short constrained fields are far more stable than free prose.

**3. The Pydantic gate earned its place on exactly one input.**
It rejected nothing across 70 well-formed runs and rejected 10 of 30 Planner
attempts on the adversarial input. A validator that never fires on normal
traffic and fires hard on pathological traffic is behaving correctly; its value
is not measured by how often it triggers.

**4. Server-side JSON enforcement and semantic validation are different layers.**
Ollama's `format` parameter guarantees the reply parses and has exactly three
string tags. It cannot express "each tag is 3–30 characters" or "the summary is
at most 25 words". Every rejection recorded in this homework was a length
violation that the JSON schema had already passed. The two layers are not
redundant.
