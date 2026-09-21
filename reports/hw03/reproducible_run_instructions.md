# Reproducible run instructions — Homework 3

Repository: https://github.com/xuwang-goldenwater/data260-9275
Tag: `hw3`

Homework 3 extends the same codebase. HW1/HW2 files are unchanged; new code is
in `code/auth_app/` (Part 1) and `code/rag_*.py` (Part 2).

## Setup (once)

```bash
cd data260-9275
conda activate data260          # Python 3.12
pip install -r requirements.txt # HW3 adds llama-index, sentence-transformers, faiss-cpu, bs4, ...
```

The first `make run-rag` downloads `sentence-transformers/all-MiniLM-L6-v2`
(~90 MB) from Hugging Face.

## Section 0 configuration

| Value | This submission |
|---|---|
| SID4 | 9275 |
| PORT_BASE | 8275 |
| PREFIX | s9275 |
| SEED | 9275 |
| VERIFY_SEED | 269275 |
| DOMAIN_ID | 3 — grocery supply and recall notices |

## Part 1 — auth app

```bash
make run-auth           # http://localhost:8275   (user admin / password password)
make demo-session       # prints Set-Cookie, logout replay and idle-timeout proof
```

Stop anything else on port 8275 first (`make run-api` from HW2 uses the same port).
Open **http://localhost:8275** in Chrome. The cookie is `Secure`; Chrome accepts
Secure cookies on `localhost` over plain http, Safari does not.

Set-Cookie header from the running server:

```bash
curl -si -X POST -d "username=admin&password=password" http://127.0.0.1:8275/login | grep -i set-cookie
```

## Part 2 — chunking comparison, in this order

```bash
make fetch-corpus       # 1. download 89 FDA notices + 21 CFR Part 7 -> reports/hw03/corpus/
                        #    writes CORPUS_MANIFEST.json and SOURCES.md
git add reports/hw03/urls.txt reports/hw03/corpus reports/hw03/CORPUS_MANIFEST.json \
        reports/hw03/SOURCES.md reports/hw03/questions.yaml
git commit -m "HW3: corpus and questions (before retrieval)"      # 2. questions BEFORE results

make run-rag            # 3. three pipelines, prints tables, writes raw/, appends RUN_LOG.txt
make rag-annotations    # 4. creates annotations.csv; fill contains_answer = yes/no
make rag-summary        # 5. recomputes the tables from raw/ into METRICS.md
make verify-hw03        # 6. writes verification.json
```

The corpus is already committed, so steps 2-6 can be re-run without step 1.
`make fetch-corpus` downloads the pages again; FDA may have edited a page since,
in which case the SHA-256 values change.
