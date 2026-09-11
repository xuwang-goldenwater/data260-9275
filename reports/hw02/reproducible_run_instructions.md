# Reproducible run instructions — Homework 2

Repository: https://github.com/xuwang-goldenwater/data260-9275
Tag: `hw2`

Homework 2 extends the Homework 1 codebase in place. Nothing was copied into
`reports/`; application code lives only in `code/` and `src/`.

## Prerequisites

| Requirement | Version used |
|---|---|
| Python | 3.12 (3.11 also fine; **3.13 breaks langchain's numpy dependency**) |
| Ollama | with `qwen3:8b` pulled (~5.2 GB) |
| RAM | 8 GB is enough but tight; close other applications before the 75-run experiment |
| Browser | any; the 375px screenshots were taken in Chrome DevTools, iPhone SE preset |

## Setup

```bash
git clone https://github.com/xuwang-goldenwater/data260-9275.git
cd data260-9275

conda create -n data260 python=3.12 -y
conda activate data260
pip install -r requirements.txt

ollama pull qwen3:8b
```

Every command below assumes `conda activate data260` has been run in that
shell. Homework 2 adds `fastapi`, `uvicorn`, `httpx`, `langgraph` and
`pydantic` to `requirements.txt`.

## Section 0 configuration

| Value | This submission |
|---|---|
| SID4 | 9275 |
| PORT_BASE | 8275 |
| PREFIX | s9275 |
| SEED | 9275 |
| VERIFY_SEED | 269275 |
| DOMAIN_ID | 3 — grocery supply and recall notices |

## Parts 1 and 2 — the web application and the API

One process serves both the page and the API on PORT_BASE.

```bash
make run-api
open http://127.0.0.1:8275
```

The record store is `code/data/recall_notices.json`. It does not exist in a
fresh clone; it is created from `code/data/recall_notices.seed.json` on first
start, which is why a clone always begins with the same three notices. To
return to that state at any time:

```bash
make reset-data
```

If port 8275 is already taken — the Homework 1 Docker container also uses it —
stop the other process first:

```bash
lsof -nP -iTCP:8275 -sTCP:LISTEN     # see what is holding it
make docker-stop                     # if it is the HW1 container
```

### Reproducing the three list states

The loading and error states are momentary by nature, so the server has two
switches that make them hold still long enough to photograph. Neither changes
the API contract and both default to off.

```bash
make run-api-demo                              # 1.5 s delay -> loading state
DEMO_FAIL_LIST=1 python code/api_server.py     # GET /api/notices returns 500 -> error state
```

The empty state needs no switch: search for a term that matches nothing, for
example `zzzz`.

### Reproducing Part 2 by hand

Add, update, delete and search from the page. Or against the API directly:

```bash
curl -s localhost:8275/api/notices | python -m json.tool
curl -s "localhost:8275/api/notices?q=onions" | python -m json.tool        # primary field
curl -s "localhost:8275/api/notices?q=cedar%20mill" | python -m json.tool  # secondary field
curl -s -X DELETE localhost:8275/api/notices/3 -w '%{http_code}\n'
```

## Part 3 — the stateful agent graph

Fast structural check first. It replaces the model with a scripted fake, so it
needs no Ollama and finishes in about a second:

```bash
python code/graph_offline_test.py          # expect 13/13 behaviour tests passed
```

One real streamed run:

```bash
make run-graph
# equivalently:  cd code && python -u agent_graph.py
```

Other inputs and settings:

```bash
cd code
python agent_graph.py --input ../reports/hw02/cases/schema_input.json
python agent_graph.py --input ../reports/hw02/cases/adversarial_input.json
python agent_graph.py --ceiling 2
python agent_graph.py --json               # one JSON record, no streaming
```

### Step 6 — the correction loop

The assignment asks for the Reviewer to be made to always return an issue, so
the graph can be watched routing the task back to the Planner. That is a flag
rather than an edit to `reviewer_node`, so the demonstration is repeatable and
the normal path is never left modified:

```bash
cd code && python -u agent_graph.py --force-reviewer-issues --ceiling 4
```

Expect Planner → Reviewer → Planner → … until the supervisor abandons the run
at turn 5.

## Part 4 — the loop-safety experiments

```bash
make run-hw02-experiments
```

75 runs — 30 + 20 + 20 + 5 — roughly 30 minutes of model time on this hardware,
closer to an hour of wall clock. Every finished run is appended to
`reports/hw02/raw/graph_runs.jsonl` immediately, and the runner skips runs
already in that file, so `Ctrl+C` loses at most the run in flight and starting
it again continues from there.

Individual experiments, and recomputing the tables without re-running anything:

```bash
cd code
python graph_experiment_runner.py --experiment ceiling2
python graph_experiment_runner.py --summarize       # rebuild CSV and metrics only
python graph_experiment_runner.py --all --restart   # ignore earlier runs
```

The frozen inputs were written to `reports/hw02/cases/` before any run and were
not edited afterwards.

## Self-check

```bash
make verify-hw02
```

Starts the FastAPI server on PORT_BASE against a **temporary** record store, so
the check never touches `code/data/recall_notices.json` or any application
file. It then exercises create / update / delete / search over HTTP, runs the
offline graph test, runs one live graph under a 240-second timeout, and
re-checks the recorded Part 4 data against the output contract.

Writes `reports/hw02/verification.json` and exits non-zero if a required check
fails. Homework 1's check still passes unchanged:

```bash
make verify-hw01
```
