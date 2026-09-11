# AI_USE.md — Homework 2

## 1. What I used an AI assistant for, and what I did myself

I used Claude as a coding assistant, in the same working mode as Homework 1.

**What the assistant did**

- Wrote `code/api_server.py`, the extended `index.html` / `app.js` / `styles.css`,
  `code/agent_graph.py`, `code/graph_experiment_runner.py`,
  `code/graph_offline_test.py` and `verify_hw02.py`.
- Drafted this report, `METRICS.md`, and the reproducible run instructions.
- Explained the parts I had not used before: LangGraph conditional edges, why a
  `TypedDict` state needs every node to return a partial update rather than
  mutate, and the difference between Ollama's server-side `format` enforcement
  and a Pydantic validator.

**What I did**

- Ran every command and every experiment myself. All 75 graph runs and all
  screenshots come from my machine.
- Made the design decisions after the options were laid out: JSON-file storage
  for the API rather than in-memory or SQLite, so the record store survives a
  restart and the screenshots are reproducible; and keeping `qwen3:8b` rather
  than substituting a faster model, so the HW2 numbers stay comparable with the
  HW1 numbers on the same input.
- Decided that Part 1's `alert()` calls from HW1 had to become in-page error
  states, since "visible error states" is what Part 1 asks for and a modal
  alert is not visible in a screenshot of the page.
- Read the adversarial traces run by run, which is how the livelock in
  `METRICS.md` was identified as a Reviewer/validator contradiction rather than
  model noise.
- Caught that the environment instructions I was given were wrong — they
  assumed a `.venv` in the repo, but Homework 1 was built in a conda
  environment named `data260`. The repo has no `.venv` and never did.

## 2. An AI output that was wrong

The first version of `supervisor_node` incremented the turn counter on **every**
visit to the supervisor:

```python
def supervisor_node(state):
    turn = state.get("turn_count", 0) + 1
    ...
```

The graph routes back through the supervisor after every agent, and it passes
through once more on the way to `END`. So a run that was correct on the first
attempt — Planner once, Reviewer once — recorded **three** turns, not two.

That is not a cosmetic off-by-one. Part 4.4 compares turn ceilings of 2 and 10.
Under this counter, a ceiling of 2 could never complete *any* run, including a
perfect one, because the third supervisor visit always tripped the ceiling
first. The comparison would have reported 0% completion against 100% and looked
like a finding about retries, when it would only have been a finding about
where a counter was placed.

## 3. How I detected it

Before running anything against the local model, the assistant wrote
`code/graph_offline_test.py`: it swaps `ModelClient` for a scripted fake that
returns a prepared reply, so the graph's control flow can be exercised in under
a second without Ollama.

One of its cases asserts that a clean run completes under ceiling 2. That case
failed, and the printed `turns=3` on a run with one Planner call and one
Reviewer call is what made the cause obvious. Running the real experiment first
would have produced 40 minutes of data that looked plausible and was not.

## 4. What I changed, and why it works now

The counter now counts **agent dispatches**, not supervisor visits. The decision
of what happens next was pulled out into one predicate that both the supervisor
and the router read:

```python
def next_worker(state):
    if state.get("status") in ("complete", "abandoned"):
        return None
    ...
    return None


def supervisor_node(state):
    pending = next_worker(state)
    if pending is None:
        return {}                    # no agent will run; nothing to count
    turn = state.get("turn_count", 0) + 1
    ...


def router_logic(state):
    worker = next_worker(state)
    return worker if worker is not None else END
```

A clean run now costs 2 turns, so ceiling 2 means "one Planner attempt and one
review, no retries" — which is the thing Part 4.4 is actually asking about. The
run data confirms it: `mean_turns` is 2.0 in both the ceiling-2 and ceiling-10
arms, and both complete 20 of 20.

The structural reason it is now correct is that the counter and the route can
no longer disagree. They are derived from the same function call, so there is
no state in which the supervisor counts a turn that the router then declines to
spend.

## A second defect, found the same way

With the counter fixed, the offline test crashed on the `.stream()` path with
`TypeError: 'NoneType' object is not iterable`. A LangGraph node that returns an
empty dict yields `None` in the stream, and the supervisor's final visit does
exactly that. `.invoke()` never surfaces it, so a run that looked fine in the
experiment runner would have failed the moment anyone streamed it — which is
precisely what Part 3 Step 6 asks for. One guard fixed it:

```python
if not update:
    continue
```

Both defects were in code that would have *appeared* to work. The offline test
is what separated "the run finished" from "the run finished for the right
reason", and it now runs as a required check inside `verify_hw02.py`.

## What I did not verify

The 100% first-attempt rate in Part 4.3 was measured on a single frozen input.
It shows the Pydantic gate does not fire on that notice; it does not show the
gate rarely fires in general. `METRICS.md` states that limit explicitly rather
than generalising from one case.
