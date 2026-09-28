.PHONY: verify-hw01 verify-hw02 run-agent run-nondeterminism run-client \
        run-api run-api-demo reset-data run-graph run-hw02-experiments \
        docker-build docker-run docker-stop \
        run-auth demo-session fetch-corpus run-rag rag-annotations rag-summary verify-hw03 \
        db-init seed run-hw04 run-frontend bench-n1 explain-index run-rag4 rag4-summary verify-hw04

PORT_BASE = 8275
IMAGE     = recall-notice-app
CONTAINER = recall-notice

# ---- Homework 1 -----------------------------------------------------------

verify-hw01:
	python verify_hw01.py

run-agent:
	cd code && python agents_demo.py

run-nondeterminism:
	cd code && python -u nondeterminism_runner.py 2>&1 | tee -a ../reports/hw01/RUN_LOG.txt

run-client:
	cd code && python -u hw1_client.py --script 2>&1 | tee -a ../reports/hw01/RUN_LOG.txt

# ---- Homework 2 -----------------------------------------------------------

verify-hw02:
	python verify_hw02.py

# Part 1 and Part 2: the front end and the API on one port.
run-api:
	python code/api_server.py

# Same server, but slow enough to photograph the loading state and able to
# fail the list request on demand for the error state.
run-api-demo:
	DEMO_DELAY_MS=1500 python code/api_server.py

# Put the record store back to the three seeded notices.
reset-data:
	rm -f code/data/recall_notices.json
	@echo "record store cleared; it is recreated from the seed file on next start"

# Part 3: one run of the stateful agent graph, streamed.
run-graph:
	cd code && python -u agent_graph.py 2>&1 | tee -a ../reports/hw02/RUN_LOG.txt

# Part 4: the full experiment set. Resumable - re-running skips finished runs.
run-hw02-experiments:
	cd code && python -u graph_experiment_runner.py --all 2>&1 | tee -a ../reports/hw02/RUN_LOG.txt

# ---- Docker (HW1 static build; stop it before using run-api on 8275) ------

docker-build:
	docker build -f code/Dockerfile -t $(IMAGE) code/web_application

docker-run: docker-build
	-docker rm -f $(CONTAINER)
	docker run -d -p $(PORT_BASE):80 --name $(CONTAINER) $(IMAGE)
	@echo "open http://localhost:$(PORT_BASE)"

docker-stop:
	-docker stop $(CONTAINER)
	-docker rm $(CONTAINER)

# ---- Homework 3 -----------------------------------------------------------

# Part 1: login / logout app on PORT_BASE (stop run-api / docker first)
run-auth:
	python code/auth_app/main.py

# Part 1: Set-Cookie flags, logout replay and idle timeout, printed step by step
demo-session:
	python code/auth_session_demo.py

# Part 2 step 1: download the corpus, write CORPUS_MANIFEST.json and SOURCES.md
fetch-corpus:
	python code/rag_fetch_corpus.py

# Part 2 step 2: three chunking pipelines. Commit questions.yaml BEFORE this.
run-rag:
	@echo "===== run-rag $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a reports/hw03/RUN_LOG.txt
	python -u code/rag_chunking.py 2>&1 | tee -a reports/hw03/RUN_LOG.txt

# Part 2 step 3: annotation sheet, then summary tables recomputed from raw/
rag-annotations:
	python code/rag_summary.py --init-annotations

rag-summary:
	python code/rag_summary.py

verify-hw03:
	python verify_hw03.py

# ---- Homework 4 -----------------------------------------------------------
# The HW3 auth app (code/auth_app) is now the MySQL-backed API for the React
# client. run-auth / demo-session / verify-hw03 describe the HW3 version: use
# `git checkout hw3` to re-run them.

HW4_LOG = reports/hw04/RUN_LOG.txt

# Part 2: create s9275_rel and its tables (drops existing tables)
db-init:
	@mkdir -p reports/hw04
	@echo "===== db-init $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u code/db_init.py 2>&1 | tee -a $(HW4_LOG)

# Part 3 step 1: 200 firms + 5000 recall notices (SEED 9275) + demo login user
seed:
	@echo "===== seed $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u code/seed_hw04.py 2>&1 | tee -a $(HW4_LOG)

# Part 1/2: API on PORT_BASE 8275 (stop run-api / run-auth / docker first)
run-hw04:
	python code/auth_app/main.py

# Part 1: React dev server on http://localhost:5173 (terminal 2)
run-frontend:
	cd frontend && npm install && npm run dev

# Part 3 steps 4-7: 180 measured requests (needs run-hw04 in another terminal)
bench-n1:
	@echo "===== bench-n1 $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u code/n1_bench.py 2>&1 | tee -a $(HW4_LOG)

# Part 3 step 8: EXPLAIN before / after the recall_date index
explain-index:
	@echo "===== explain-index $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u code/explain_index.py 2>&1 | tee -a $(HW4_LOG)

# Part 4: A/B/C comparison + k-sweep (needs `ollama serve` with qwen3:8b).
# Commit reports/hw04/rag_questions.yaml BEFORE running this.
run-rag4:
	@echo "===== run-rag4 $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u code/rag.py 2>&1 | tee -a $(HW4_LOG)

# Part 4: evaluation table, after filling correct_answer / grounded in raw/rag_eval.csv
rag4-summary:
	python code/rag.py --summary

verify-hw04:
	@echo "===== verify-hw04 $$(date '+%Y-%m-%d %H:%M:%S') =====" | tee -a $(HW4_LOG)
	python -u verify_hw04.py 2>&1 | tee -a $(HW4_LOG)
