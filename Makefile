.PHONY: verify-hw01 verify-hw02 run-agent run-nondeterminism run-client \
        run-api run-api-demo reset-data run-graph run-hw02-experiments \
        docker-build docker-run docker-stop

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
