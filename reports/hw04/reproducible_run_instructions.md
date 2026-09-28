# Reproducible run instructions — Homework 4

Repository: https://github.com/xuwang-goldenwater/data260-9275
Tag: `hw4`

## Setup (once)

```bash
cd data260-9275
conda activate data260                # Python 3.12
pip install -r requirements.txt       # HW4 adds sqlalchemy, pymysql, cryptography, email-validator
cp .env.example .env                  # if .env does not exist yet
# edit .env: MYSQL_USER / MYSQL_PASSWORD for your local MySQL 8.0
```

MySQL 8.0 must be running (macOS: System Settings → MySQL → Start).
Node 18+ is needed for the React client (`node -v`).

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
| Local model | qwen3:8b (Ollama), embeddings all-MiniLM-L6-v2 |

## Run order

Terminal 1 is the API, terminal 2 is everything else. Stop anything else on
port 8275 first (`make run-api`, `make run-auth`, Docker).

```bash
# Part 2 + Part 3 step 1 - schema, seed data, demo login user
make db-init
make seed

# Part 1 + Part 2 - API (terminal 1) and React client (terminal 2)
make run-hw04                     # http://localhost:8275/docs
make run-frontend                 # http://localhost:5173  (use "localhost", not 127.0.0.1)
# login: demo@s9275.example.com / recall-demo-9275

# Part 3 - with the API running
make bench-n1                     # 180 requests -> raw/n1_requests.csv, n1_table.md
make explain-index                # EXPLAIN before/after -> raw/explain_before_after.txt

# Part 4 - Ollama running with qwen3:8b; commit rag_questions.yaml first
make run-rag4                     # raw/rag_*.{txt,jsonl,md,json}, rag_eval.csv
#   fill correct_answer + grounded (yes/no) in reports/hw04/raw/rag_eval.csv
make rag4-summary                 # raw/rag_eval_table.md

# self-check (starts the API itself if it is not running)
make verify-hw04                  # -> reports/hw04/verification.json
```

`make bench-n1` must run before `make explain-index` if you want the
benchmark to be measured without the recall_date index (the index script
leaves the index in place). Re-running `make seed` restores the 5,000 rows
but keeps the index; `make db-init` removes it.

## Postman

Import `reports/hw04/postman_collection.json`. Run "Login" first; Postman
stores the `s9275_session` cookie for localhost and sends it with the other
requests. The response headers `X-SQL-Total`, `X-SQL-List` and
`X-Server-Time-Ms` show the statement count and server time of each call.
