.PHONY: verify-hw01 run-agent run-nondeterminism run-client docker-build docker-run docker-stop

PORT_BASE = 8275
IMAGE     = recall-notice-app
CONTAINER = recall-notice

verify-hw01:
	python verify_hw01.py

run-agent:
	cd code && python agents_demo.py

run-nondeterminism:
	cd code && python -u nondeterminism_runner.py 2>&1 | tee -a ../reports/hw01/RUN_LOG.txt

run-client:
	cd code && python -u hw1_client.py --script 2>&1 | tee -a ../reports/hw01/RUN_LOG.txt

docker-build:
	docker build -f code/Dockerfile -t $(IMAGE) code/web_application

docker-run: docker-build
	-docker rm -f $(CONTAINER)
	docker run -d -p $(PORT_BASE):80 --name $(CONTAINER) $(IMAGE)
	@echo "open http://localhost:$(PORT_BASE)"

docker-stop:
	-docker stop $(CONTAINER)
	-docker rm $(CONTAINER)
