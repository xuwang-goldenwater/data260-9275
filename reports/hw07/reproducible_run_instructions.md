# HW7 — reproducible run instructions (Xu Wang, s9275)

Repo root, conda env `data260`, MySQL 8 with `s9275_rel` (HW4/HW5 schema), Ollama with
`qwen2.5:3b`. `pip install -r requirements.txt` (adds pyjwt, ruff, pre-commit). Every target
appends its output to `reports/hw07/RUN_LOG.txt`. Long runs: prefix with `caffeinate -i`.

| Part | Command | Output |
|---|---|---|
| 1 users + roles | `make users-hw07` | `users.username`, `users.role`, 3 accounts |
| 1 API | `make run-hw07` | http://localhost:8275/docs; Postman `reports/hw07/postman_collection.json` |
| 1 lint | `pre-commit install`, then `git commit` | Ruff runs on staged files |
| 2 one task | `make agent-hw07 TASK=A` (A, B, C, error) | tool log + deterministic check |
| 2 reliability | `make reliability-hw07` (~12 min) | `raw/reliability_*.{csv,jsonl,json}` |
| 3 Reflexion | `make reflexion-hw07` (~17 min) | `raw/reflexion_*`, `raw/reflections.jsonl` |
| 4 data | `make bike-data` (~5 min, network) | `raw/bike/{membership,payperuse}_wins.csv` |
| 4 agent (terminal) | `make bike-agent S=membership` | `raw/bike/runs/*.json`, snapshot in `raw/bike/snapshots/` |
| 4 UI | `make run-bike` (stop run-hw07 first) | http://localhost:8275 — upload a CSV, Run |
| 5 attacks | `make bike-attacks` (~10 min) | `raw/bike/attack_matrix.csv`, `attack_summary.json` |
| 6 file tools | `make test-file-tools` | `raw/safety_gate_results.csv`, `file_tools_integration.json` |
| Self-check | `make verify-hw07` (commit code first) | `reports/hw07/verification.json` |

Seeds: SEED 9275 (data sampling), 9276–9296 (reliability), 9376–9384 (Reflexion comparison).
The pricing page is fetched live; the snapshot text and SHA-256 used by each run are saved, so a
later page change shows up as a different SHA-256 rather than silently different numbers.
