# data260-9275

DATA 260 coursework repository. Application code is shared across all homework
assignments; per-assignment evidence lives under `reports/hwNN/`.

**Repository:** https://github.com/xuwang-goldenwater/data260-9275

## Layout

```
code/                  shared application code (extended each homework)
  web_application/     web app source
  agents_demo.py       agent demo entrypoint
  hw1_client.py        HW1 driver script
  Dockerfile           container image for the application
src/
  model_client.py      model adapter (required exact path)
reports/
  hw01/                HW1 report, metrics, logs, raw outputs
  hw02/ hw03/          future assignments
AGENT.md               agent design, tools, prompts
DOMAIN_SCHEMA.md       domain data schema
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then fill in your API key
python code/hw1_client.py --help
```

## Collaborators

- Sbnikitha
- supriyaselvanganesan

## Conventions

- Do **not** copy application code into `reports/`. Reports hold evidence only.
- The model adapter must stay at `src/model_client.py`.
