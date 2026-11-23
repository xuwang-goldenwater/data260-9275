# Stock Watch — DATA 260 always-on agent demo kit

An always-on monitor for a stock watchlist. It tells you only when something material changes:
a large daily price move or a significant new SEC 8-K filing. It reports what changed. It never
gives buy, sell or hold advice.

Built to run on Meta Muse's free tier (any agent with a terminal also works). The agent judges materiality.
`watch.py` (Python 3.8+, standard library only) does everything that must survive restarts and
must not depend on model memory: approved-source allowlist, fetching, stable effect IDs (SEC
accession numbers, ticker + date for price moves), deduplication, an effect ledger (no double
alerts), checkpoints (resume after a crash), a prompt-injection guard, traces and metrics.

| File | What it is |
|---|---|
| `watch.py` | The tool the agent calls. `python3 watch.py -h` lists commands |
| `sources.json` | Approved sources. Live: Stooq daily prices, SEC EDGAR 8-K feeds (AAPL, NVDA, MSFT by default). Demo: fixtures |
| `policy.md` | Notify / digest / ask / quiet, with a scoring guide; no-advice rule |
| `fixtures/day1`, `fixtures/day2` | Demo data for three fictional companies (NBRX, CBDS, LKSP) |
| `golden/gold_demo.json` | Expected decisions for the demo fixtures |
| `golden/gold_template.json`, `fixtures/hw_template/` | Homework starters |
| `demo_test.sh` | Runs the whole demo with a scripted judge (no LLM) |
| `MUSE_SETUP.md` | Copy-paste prompts for Muse: install, standing instructions (memory), schedule, demo |

Before live use, put your contact email in `user_agent` in `sources.json`: the SEC asks
automated clients to identify themselves. Change the watchlist by editing `tickers` and `ciks`.

All demo companies, filings, prices and news items are fictional and labeled as such.

Muse-specific design: short outputs to save free-tier usage; a 3-day price lookback so a missed
or late scheduled run catches up without repeating alerts; `snapshot` / `restore` so the ledger
survives if the cloud computer is reset; `metrics --usage-tokens` to report usage per accepted alert.

Quick check: `bash demo_test.sh` · Reset: `python3 watch.py reset --yes && python3 watch.py init`
