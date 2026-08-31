# Reproducible run instructions — Homework 1

Repository: https://github.com/xuwang-goldenwater/data260-9275
Tag: `hw1`

## Prerequisites

| Requirement | Version used |
|---|---|
| Python | 3.12 (3.11 also fine; **3.13 breaks langchain's numpy dependency**) |
| Ollama | with `qwen3:8b` pulled (~5.2 GB) |
| Docker Desktop | for the local container step |
| AWS CLI v2 | for the ECS step only |
| RAM | 8 GB is enough but tight; close other applications before the 40-run experiment |

## Setup

```bash
git clone https://github.com/xuwang-goldenwater/data260-9275.git
cd data260-9275

conda create -n data260 python=3.12 -y
conda activate data260
pip install -r requirements.txt

ollama pull qwen3:8b
```

Every Python command below assumes `conda activate data260` has been run in
that shell.

## Part 1 — web application

```bash
open code/web_application/index.html
```

Open the browser console (`Cmd+Option+J` on macOS). Fill the form and submit.
The console prints the JSON string, the destructured fields, the object with
`submissionDate` added, and the submission count.

Validation to exercise:
- a description of 25 characters or fewer triggers an alert
- an unchecked terms box triggers an alert

## Deployment — Docker

```bash
make docker-run          # build and run
open http://localhost:8275
make docker-stop         # clean up
```

Or without make:

```bash
docker build -f code/Dockerfile -t recall-notice-app code/web_application
docker run -d -p 8275:80 --name recall-notice recall-notice-app
```

Port 8275 is `PORT_BASE` from Section 0.

## Deployment — AWS ECS

```bash
aws login                                    # or: aws configure
aws ecr create-repository --repository-name recall-notice-app --region us-east-1

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# --platform is required on Apple silicon; Fargate runs x86_64
docker build --platform linux/amd64 -f code/Dockerfile \
  -t recall-notice-app:amd64 code/web_application
docker tag recall-notice-app:amd64 \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/recall-notice-app:latest
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/recall-notice-app:latest
```

Then in the ECS console, region **us-east-1**:

1. Create cluster `data260-hw1-cluster`, infrastructure AWS Fargate.
2. Create task definition `recall-notice-task`: Fargate, **Linux/X86_64**,
   0.25 vCPU, 0.5 GB, container port **80**, image = the ECR URI above.
3. Create service `recall-notice-service`, launch type FARGATE, desired tasks
   **1**, new security group allowing inbound HTTP from 0.0.0.0/0, and
   **Public IP turned on**.
4. Wait for the task to reach `Running`, then read its public IP:

```bash
TASK=$(aws ecs list-tasks --cluster data260-hw1-cluster --region us-east-1 \
  --query 'taskArns[0]' --output text)
ENI=$(aws ecs describe-tasks --cluster data260-hw1-cluster --tasks $TASK \
  --region us-east-1 \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)
aws ec2 describe-network-interfaces --network-interface-ids $ENI \
  --region us-east-1 \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

Open `http://<PUBLIC_IP>` — plain HTTP, no port suffix.

**Delete the service and cluster afterwards.** Fargate bills while the task runs.

## Part 2 — agent pipeline

```bash
make run-agent
# equivalently:  cd code && python agents_demo.py
```

Other inputs:

```bash
cd code
python agents_demo.py --input ../reports/hw01/cases/nondeterminism_input.json
python agents_demo.py --title "..." --content "..." --temperature 0.7
python agents_demo.py --quiet          # only the final Publish JSON
```

## Part 3 — non-determinism experiment

```bash
make run-nondeterminism
```

40 runs, roughly 15–25 minutes on this hardware. Progress is written to
`reports/hw01/raw/nondeterminism_runs.jsonl` after every run, so an interrupted
run resumes rather than restarting. To recompute the tables from existing data
without re-running the model:

```bash
cd code && python nondeterminism_runner.py --report-only
```

## Part 4 — model client

```bash
make run-client                        # the recorded five-turn session
cd code && python hw1_client.py        # interactive
```

Interactive commands: `/stats`, `/history`, `/quit`. Paste code, then a blank
line to send.

## Self-check

```bash
make verify-hw01
```

Writes `reports/hw01/verification.json` and exits non-zero if any required
check fails.
