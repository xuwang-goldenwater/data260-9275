# AI use — Homework 4

## 1. What I used an AI assistant for, and what I did myself

**AI assistant (Claude):**

- Wrote the first version of the code after I approved the design: the MySQL-backed
  API in `code/auth_app/`, the schema/seed scripts, the React client in `frontend/`,
  `n1_bench.py`, `explain_index.py`, `rag.py`, `verify_hw04.py`, and the Postman
  collection. It tested these in its own environment against MySQL 8.0 and with
  a headless browser before handing them over.
- Drafted the six RAG questions.

**Me:**
- Read the assignment and the instructor's DATA236 demo and listed the gaps between
  them (the demo logs in with a user_id and no password, protects only the list
  endpoint, and stores naive datetimes in a time-zone column).
- Made the design decisions: extend the HW3 auth app instead of HW2's `api_server.py`
  and keep HW2 untouched; put the React client in a root-level `frontend/`; model the
  domain as recall notices + firms; pass the record id to `/update` and `/delete`
  through router state so the routes match the assignment literally.
- Set up and ran everything on my Mac (MySQL 8.0.43, conda env, Ollama qwen3:8b), and
  fixed the environment problems I ran into (empty MySQL password in `.env`, running
  in the conda `base` env with Python 3.13 instead of `data260`).
- Tested the React app by hand, took the Postman / database / UI screenshots.
- Reviewed the RAG questions and committed them before the retrieval run.
- Read every RAG answer against the retrieved chunks and filled `correct_answer` and
  `grounded` in `raw/rag_eval.csv` myself.

## 2. One AI-produced output that was wrong

The first version of `rag.py` let sentence-transformers choose its device. On my
M1 Mac it chose Apple's GPU backend (MPS) for the MiniLM embeddings, while Ollama was
using the same GPU for qwen3:8b. The run finished without crashing, but the retrieval
was wrong: config B retrieved almost nothing relevant (correct retrieval 1/4) and config
C refused all six questions, including Q1–Q4, because every candidate chunk scored
below the 0.35 threshold.

## 3. How I detected the problem

The same question got different retrieval results in different configurations. Config
C searches a pool of 2k candidates, so its list must contain B's top 3 with the same
scores — but for Q4 the top score was 0.65 in B and 0.11 in C, and for Q1 B's first
hit was a lettuce recall while C's was the a2 infant-formula notice. That can only
happen if the same question produces different embeddings on different calls.
`RUN_LOG.txt` then showed the cause: Metal errors
`Insufficient Memory (kIOGPUCommandBufferCallbackErrorOutOfMemory)` on the
`Apple M1` device during the run. The GPU ran out of memory and the embedding
calls silently returned bad vectors.

## 4. What I changed and why it works now

- Embeddings run on the CPU (`SentenceTransformer(..., device="cpu")`), so they no
  longer compete with Ollama for GPU memory. MiniLM is small, so the index still
  builds in seconds.
- Each question is embedded once and cached, so B, C and every k in the sweep use the
  identical query vector.
- Every FAISS search is cross-checked against a plain numpy dot product over all
  chunks; a mismatch stops the run.
- Before any model call, `self_check()` re-encodes 8 chunks and all 6 questions and
  stops the run if the vectors differ at all. The check result and the package versions
  are saved in `raw/rag_run_meta.json`.

In the re-run the self-check reported a difference of 0.0 for both chunks and queries,
B and C show the same ranking and scores for every question (Q4: 0.6502 in both),
correct retrieval rose to 3/4 for B and C, and C answered Q1–Q4 and refused only Q5 and
Q6. The questions file was not changed between the two runs, so the commit that fixed
the questions before retrieval still holds.
