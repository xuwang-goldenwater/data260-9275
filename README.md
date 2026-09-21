# data260-9275

DATA 260 coursework repository. Application code is shared across all homework
assignments; per-assignment evidence lives under `reports/hwNN/`.

**Repository:** https://github.com/xuwang-goldenwater/data260-9275

## Layout

```
code/                        shared application code (extended each homework)
  web_application/           web app source: index.html, app.js, styles.css
  data/                      record store seed for the API
  agents_demo.py             HW1 Planner -> Reviewer -> Finalizer pipeline
  hw1_client.py              HW1 driver script
  nondeterminism_runner.py   HW1 Part 3 experiment
  api_server.py              HW2 FastAPI backend on PORT_BASE 8275
  agent_graph.py             HW2 LangGraph supervisor graph
  graph_experiment_runner.py HW2 Part 4 experiments
  graph_offline_test.py      HW2 graph behaviour test, no model required
  auth_app/                  HW3 Part 1 login/logout app (FastAPI + Jinja2 + Bootstrap)
  auth_session_demo.py       HW3 Part 1 cookie / logout / idle-timeout proof
  rag_fetch_corpus.py        HW3 Part 2 corpus download + manifest
  rag_chunking.py            HW3 Part 2 token / semantic / sentence-window comparison
  rag_summary.py             HW3 Part 2 summary tables recomputed from raw/
  Dockerfile                 container image for the static HW1 page
src/
  model_client.py            model adapter (required exact path)
reports/
  hw01/                      HW1 report, metrics, logs, raw outputs
  hw02/                      HW2 report, metrics, logs, raw outputs
  hw03/                      HW3 corpus, questions, metrics, logs, raw outputs
verify_hw01.py               HW1 self-check
verify_hw02.py               HW2 self-check
verify_hw03.py               HW3 self-check
AGENT.md                     system prompt for hw1_client.py
DOMAIN_SCHEMA.md             domain data schema
```

## Quick start

```bash
conda create -n data260 python=3.12 -y
conda activate data260
pip install -r requirements.txt
ollama pull qwen3:8b

make run-api            # HW2 web app + API on http://127.0.0.1:8275
make run-graph          # HW2 stateful agent graph, one streamed run
make verify-hw02        # self-check
```

Python 3.11 or 3.12. **3.13 breaks langchain's numpy dependency.**

## Collaborators

- Sbnikitha
- supriyaselvanganesan

## Conventions

- Do **not** copy application code into `reports/`. Reports hold evidence only.
- The model adapter must stay at `src/model_client.py`.

## Section 0 configuration

Fixed for the semester, derived from SID4 = 9275.

| Value | This repository |
|---|---|
| PORT_BASE | 8275 |
| PREFIX | s9275 |
| SEED | 9275 |
| VERIFY_SEED | 269275 |
| DOMAIN_ID | 3 — grocery supply and recall notices |

## Homework 3 — what was added

- **Part 1** — `code/auth_app/` builds on the instructor's starter: port 8275,
  Bootstrap alert on a failed login, a Secure/HttpOnly/SameSite session cookie,
  and a server-side session table so a logged-out or idle (15 min) cookie
  cannot be replayed. `make demo-session` prints the proof.
- **Part 2** — `code/rag_chunking.py` compares LlamaIndex token, semantic and
  sentence-window chunking on 89 FDA food recall notices plus 21 CFR Part 7.
  Steps are in `reports/hw03/reproducible_run_instructions.md`.

## Homework 2 — what was added

Homework 2 extends this codebase rather than copying it.

- **Part 1** — `code/web_application/styles.css` is new; `index.html` and
  `app.js` gained a list view, a search box and visible loading, empty and
  error states, and stay usable at 375px. Every Homework 1 requirement in those
  two files still passes `verify_hw01.py`.
- **Part 2** — `code/api_server.py` serves the page and a `RecallNotice` REST
  API on PORT_BASE 8275, with create, update, delete and search over a JSON
  record store.
- **Part 3** — `code/agent_graph.py` refactors the Homework 1 sequential
  pipeline into a LangGraph `StateGraph` with a supervisor, conditional edges
  and a correction loop. Every model call still goes through
  `src/model_client.py`.
- **Part 4** — a Pydantic gate on the Planner's output, a retry path that feeds
  the validation error back, and 75 recorded runs in `reports/hw02/raw/`.
  Findings are in `reports/hw02/METRICS.md`.

## Homework 1 — Part 4 conceptual answers

Measured in one five-turn session with `qwen3:8b` at temperature 0.0, system
prompt `AGENT.md` (1,212 characters). Full transcript in
`reports/hw01/RUN_LOG.txt`.

| Turn | Input tokens | Output tokens | Latency (ms) |
|---|---|---|---|
| 1 | 344 | 25 | 17,715 |
| 2 | 463 | 101 | 12,289 |
| 3 | 622 | 118 | 16,385 |
| 4 | 774 | 35 | 5,480 |
| 5 | 834 | 244 | 24,959 |
| **Total** | **3,037** | **523** | — |

Serialized history: 3,359 characters after turn 3, 5,030 after turn 5.

### Why is prior conversation context resent with every turn?

Because the model holds no state between calls. Each request is independent;
the server keeps nothing from the previous one. Anything the model needs to
know has to be inside the request.

Turn 4 shows this directly. The question was 108 characters — roughly 25
tokens — but the turn billed 774 input tokens. The other ~750 were the earlier
conversation being replayed. That replay is what let the model answer "of the
three functions I have shown you so far" correctly; with only the 25-token
question it would have had no idea which three functions were meant.

This is the same statelessness that REST requires of a web service: the server
does not remember the client, so the client carries the context.

### How is a system prompt different from a user message?

Three ways, all visible in this session.

- **Position and persistence.** The system prompt is message index 0 and is
  resent unchanged on every turn. User messages accumulate behind it.
- **Purpose.** It sets standing rules for how to answer, rather than asking a
  question to be answered. `AGENT.md` never asks for anything; it constrains
  the shape of every reply.
- **Cost.** Its 1,212 characters were billed in all five turns. A system prompt
  is a fixed tax on every request, not a one-time setup cost.

It is not, however, an enforcement mechanism. On turn 5 the model produced 13
bullets when `AGENT.md` caps replies at 6, because the user's request ("list
every defect across the conversation") conflicted with the cap and the model
chose the request. A system prompt is a strong prior, not a constraint — which
is why `hw1_client.py` checks compliance in code rather than assuming it.

### Why do input tokens grow over a conversation?

Every turn sends the system prompt, every previous user message, every previous
assistant reply, and the new message. Nothing is ever removed, so the request
gets longer each time: 344 → 463 → 622 → 774 → 834.

Each increase tracks what was added since the last turn. Input rose 159 tokens
from turn 2 to turn 3, and turn 2's reply was 101 tokens plus the new question.

The cumulative effect is lopsided: 3,037 input tokens against 523 output
tokens. **85% of everything processed was input, and most of that was history
being re-read.** Because turn *n* carries everything before it, total tokens
over a conversation grow roughly with the square of the turn count, not
linearly.

### What eventually limits that growth?

The context window — the maximum number of tokens the model can accept in one
request. Once history plus the new message exceeds it, the request either fails
or the oldest messages are silently dropped, and the model forgets the start of
the conversation without saying so.

For this setup, `ollama show qwen3:8b` reports a context length of **40,960
tokens**. Input reached 834 tokens by turn 5 and grew by roughly 120-150 tokens
per turn, that growth being the previous reply plus the new question. At that
rate the window fills somewhere around turn 300. The effective ceiling can be
lower still: the running server's `num_ctx` may be set below what the model
supports, and whichever number is smaller is the one that applies.

Before that hard ceiling, cost and latency bite first. Two practical notes from
this session's timings:

- Latency tracks **output** tokens, not input. Turn 4 read 774 input tokens and
  finished in 5.5 s because it wrote only 35 tokens; turn 5 read a similar 834
  and took 25.0 s because it wrote 244. Input is processed in one parallel
  prefill pass; output is generated one token at a time.
- Input is therefore cheap per token but grows without bound, which is what
  later techniques address: trimming or summarising old turns, retrieving only
  relevant history instead of all of it, and caching the unchanged prefix so
  the same prefill is not paid for repeatedly.
