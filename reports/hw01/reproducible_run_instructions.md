# Reproducible run instructions — Homework 1

## 1. Environment

```bash
git clone https://github.com/<your-username>/data260-9275.git
cd data260-9275
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your API key
```

Python: 3.12. Pinned dependencies are in `requirements.txt`.

## 2. Run

```bash
python code/hw1_client.py --n 1
```

Raw output lands in `reports/hw01/raw/`.

## 3. Docker (alternative)

```bash
docker build -f code/Dockerfile -t data260-hw1 .
docker run --rm --env-file .env data260-hw1
```

## 4. Expected output

TODO — describe what a successful run prints and writes.
