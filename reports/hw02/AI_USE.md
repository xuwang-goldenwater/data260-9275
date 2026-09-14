# AI_USE.md — Homework 2

## 1. What I used an AI assistant for, and what I did myself

I used Claude as a coding assistant. The work went in four stages.

**I decided the structure first.**

Before any code was written I fixed four things:

- The field names live in one file, `DOMAIN_SCHEMA.md`, which I wrote in HW1. The
  same names are used by the HTML ids, the JavaScript keys, the API request model
  and the agent input. They have to match exactly in all four places.
- The Planner and Reviewer split carries over from HW1. I did not redesign it.
- HW2 extends the HW1 files in place. It does not copy them. This means
  `verify_hw01.py` has to keep passing against the changed files.
- The graph is a Supervisor plus two workers. The stop rule sits in the
  Supervisor only, not in the workers.

**The assistant wrote and debugged the code.**

It wrote `code/api_server.py`, the extended `index.html`, `app.js` and
`styles.css`, `code/agent_graph.py`, `code/graph_experiment_runner.py`,
`code/graph_offline_test.py` and `verify_hw02.py`. It also drafted `METRICS.md`,
the run instructions, and the first version of this file.

It explained three things I had not used before: LangGraph conditional edges, why
a `TypedDict` state needs every node to return a partial update instead of
changing the state directly, and the difference between Ollama's `format`
parameter and a Pydantic validator.

**I made the design decisions.**

Each one had an alternative that I rejected.

- **JSON file storage, not in-memory and not SQLite.** The lecture demo used an
  in-memory list. That is simpler, but the records are lost on every restart, so
  nobody else could reproduce my screenshots. SQLite is more than Part 2 asks for
  and is one more thing that can break. A seeded JSON file means a fresh clone
  always starts with the same three notices.
- **Keep `qwen3:8b`. Do not use a smaller model.** The assignment allows a
  documented substitute. A smaller model would have cut the 75 runs from about an
  hour to about fifteen minutes. I kept the HW1 model so the HW2 numbers can be
  compared with the HW1 numbers on the same input. That comparison is what
  produced the finding about the changed tag in `METRICS.md`.
- **Replace HW1's `alert()` calls with error messages inside the page.** Part 1
  asks for visible error states. An alert is an operating system window. It is
  not part of the page, it cannot be screenshotted in place, and it disappears
  when you click it. The two validation rules did not change, which is why
  `verify_hw01.py` still finds them.
- **Two clicks to delete instead of `confirm()`.** Same reason. `confirm()` also
  blocks JavaScript until the user clicks, which would break any automated test.
- **Make the Step 6 loop test a command-line flag, not a temporary code edit.**
  The assignment says to change the Reviewer so it always objects. If I edit the
  code by hand I have to remember to undo it, and any run I do before undoing it
  is wrong without any warning. A flag can be run again by anyone and leaves the
  normal path alone.

**I ran everything, checked it, and I am responsible for the result.**

All 75 graph runs, all the screenshots and all the self-checks were run on my
machine.

I also found two problems that were not in the code. The setup instructions I was
given assumed a `.venv` folder inside the repository. HW1 was built in a conda
environment called `data260` and there is no `.venv`. Later the error-state switch
looked like it did nothing. The reason was that an older server still had port
8275, so the new one never started and the browser was still talking to the old
one. `lsof -nP -iTCP:8275 -sTCP:LISTEN` showed this.

I checked the main claims in `METRICS.md` against the raw data in
`reports/hw02/raw/graph_runs.jsonl` instead of trusting the summary. I checked
that the two homeworks really do publish different tags on the same input, that
the five adversarial runs really are identical and not just similar, and that the
two turn ceilings really did use the same number of tokens.

## 2. An AI output that was wrong

The first version of `supervisor_node` added one to the turn counter every time
the Supervisor ran:

```python
def supervisor_node(state):
    turn = state.get("turn_count", 0) + 1
    ...
```

The graph goes back through the Supervisor after every agent, and once more on
the way to `END`. So a run that was correct the first time, with one Planner call
and one Reviewer call, counted **three** turns instead of two.

This is not just an off-by-one. Part 4.4 compares a ceiling of 2 with a ceiling
of 10. With this counter, a ceiling of 2 could never finish any run at all, even
a correct one, because the third visit to the Supervisor always hit the ceiling.
The comparison would have shown 0% against 100%. That looks like a result about
retries. It is really a result about where the counter was put.

## 3. How it was detected

`code/graph_offline_test.py` replaces `ModelClient` with a fake that returns
prepared answers. This means the graph can be tested in about one second without
Ollama.

One of its cases checks that a clean run finishes under a ceiling of 2. That case
failed. It printed `turns=3` for a run with one Planner call and one Reviewer
call, which made the cause easy to see.

I ran the experiment only after this test passed. If I had run it first I would
have had forty minutes of data that looked fine and was not.

## 4. What changed, and why it works now

The counter now counts how many times an agent is given work, not how many times
the Supervisor runs. The decision about what happens next was moved into one
function that both the Supervisor and the router call:

```python
def next_worker(state):
    if state.get("status") in ("complete", "abandoned"):
        return None
    ...
    return None


def supervisor_node(state):
    pending = next_worker(state)
    if pending is None:
        return {}                    # no agent will run, so nothing to count
    turn = state.get("turn_count", 0) + 1
    ...


def router_logic(state):
    worker = next_worker(state)
    return worker if worker is not None else END
```

A clean run now costs 2 turns. So a ceiling of 2 means one Planner attempt and
one review, with no retry. That is what Part 4.4 is actually asking about. The
recorded data agrees: `mean_turns` is 2.0 in both arms and both finish 20 of 20.

It works now because the counter and the router call the same function. They
cannot disagree. There is no state where the Supervisor counts a turn that the
router then does not use.

### A second problem, found the same way

After the counter was fixed, the offline test failed on the `.stream()` path with
`TypeError: 'NoneType' object is not iterable`. A LangGraph node that returns an
empty dict shows up as `None` in the stream, and the Supervisor's last visit
returns an empty dict. `.invoke()` does not show this at all. The experiment
runner uses `.invoke()`, so all 75 runs would have finished without hitting it,
and Part 3 Step 6, which needs `.stream()`, would have failed during the demo.
One line fixed it:

```python
if not update:
    continue
```

Both problems were in code that looked like it worked.
