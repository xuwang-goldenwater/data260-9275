# Reproducible run instructions — Homework 5

Repository: https://github.com/xuwang-goldenwater/data260-9275
Tag: `hw5`

## Setup (once)

```bash
cd data260-9275
conda activate data260                # Python 3.12
pip install -r requirements.txt       # HW5 adds mcp[cli] 1.x (pinned below 2)
cp .env.example .env                  # if .env does not exist yet
# edit .env: MYSQL_USER / MYSQL_PASSWORD for your local MySQL 8.0
cd frontend && npm install && cd ..   # HW5 adds @reduxjs/toolkit, react-redux, axios
ollama pull qwen3:8b
```

MySQL 8.0 and Ollama must be running. Node 18+ is needed for the React client
and for the MCP Inspector (`npx`).

## Section 0 configuration

| Value | This submission |
|---|---|
| SID4 | 9275 |
| PORT_BASE | 8275 |
| PREFIX | s9275 |
| SEED | 9275 |
| VERIFY_SEED | 269275 |
| DOMAIN_ID | 3 — grocery supply and recall notices |
| Database | MySQL 8.0, `s9275_rel` |
| Local model | qwen3:8b (Ollama, temperature 0) |

## Run order

Terminal 1 is the API, terminal 2 is everything else.

```bash
# Part 1 - database: HW4 schema and seed data, then the HW5 migration (run once)
make db-init
make seed
make migrate-hw05
make db-show                      # both table definitions and their first rows

# Part 1 - API (terminal 1) and React + Redux client (terminal 2)
make run-hw05                     # http://localhost:8275/docs
make run-frontend                 # http://localhost:5173  (use "localhost", not 127.0.0.1)
# login: demo@s9275.example.com / recall-demo-9275

# Part 2 - MCP servers in the MCP Inspector (one at a time; needs internet for 2A)
make inspect-meals
make inspect-domain
make capture-meals                # the same calls through the Inspector CLI -> raw/
make capture-domain

# Part 3
make contracts                    # TOOL_CONTRACTS.md from the models and raw/
make retry-demo                   # first-attempt success, fail then succeed, fail after all retries
make fault-injection              # 150 calls -> raw/fault_injection_calls.csv, _summary.json

# Part 4 - offline: no MySQL, no network, no model
make test-tools

# Part 5 - needs Ollama
make safety-demo
make agent-scenarios              # five scenarios -> raw/agent_scenarios.json, agent_runs.jsonl

# self-check (starts the API and both MCP servers itself)
make verify-hw05                  # -> reports/hw05/verification.json
```

`make migrate-hw05` changes the tables in place and can run only once on a
database. To start again: `make db-init`, `make seed`, `make migrate-hw05`.

The MCP Inspector is started with `npx @modelcontextprotocol/inspector`, not
`mcp dev`: `mcp dev` runs the server through `uv` with the newest MCP SDK
(2.x), and this code uses the pinned 1.x. In the Inspector form, enter invalid
values with "Edit as JSON"; the form otherwise changes an out-of-range number
to the nearest allowed value before sending it.

## Postman

Import `reports/hw05/postman_collection.json`. Send the requests in order,
once each, starting with "Login". "Create firm" and "Create notice" store the
new ids in collection variables that the later requests use, and the "Delete"
folder removes both records again.
