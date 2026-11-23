# HW11 AI_USE — Xu Wang

**1. What I used an AI assistant for, and what I did myself.**

I used two AI systems. Meta Muse is the system under test: it ran the monitor, scored every candidate and made every notify / digest / ask / quiet decision in this report. Separately, I used Claude (Anthropic) as an assistant for building and analysing it.
Claude read the starter kit and pointed out how it behaves at the edges (a move exactly at the threshold, a missing price row, the injection regex, a news item that shares a filing's accession number); proposed the watchlist, the 12 golden cases and the threshold rule; pulled one year of daily prices and computed the volatility table; wrote `sources.json`;
I wrote `policy.md`, the fixtures, `gold_hw11.json`, the three changes to `watch.py`, and drafted METRICS.md and this report.
I also chose the watchlist, confirmed the per-ticker thresholds after seeing the volatility numbers, decided that a product-recall 8-K is `notify`, approved each golden label before it was committed (`7a5c5a6`, before any agent run), sent every Muse prompt myself, judged each Muse reply against the expected result, asked the follow-up questions that exposed two failures (where the resume folder came from; the retry that skipped `decide`), ran all git commands, and took every screenshot.

**2. One AI-produced output that was wrong.**

Claude's first threshold design put KR with KO in a "steady" group (digest 2%, notify 4%) and NVDA with TSLA in a "volatile" group. It was based on what the companies are (a grocer and a beverage maker against a chipmaker and a carmaker), not on data.

**3. How I detected it.**

I asked Claude to fetch the actual daily prices and compute the volatility before I accepted the thresholds. Over 250 trading days KR's daily sigma was 1.90%, 1.6 times KO's 1.19% and closer to NVDA's 2.60%; KR had 3 days of 5% or more, KO had none. With one 4% notify line, KR would have alerted on 7 days and KO on 1.

**4. What I changed and why it works now.**

The groups were dropped: every ticker has its own source in `sources.json` and its own line in `policy.md`, set at about 1.5 sigma (digest) and 3 sigma (notify). Measured on the same year, each ticker now reaches its notify line 2-4 days and its digest band 19-25 days (`VOLATILITY.md`), so the four stocks produce a similar amount of signal.

A second AI error came out of the live runs. Claude's `sources.json` kept two kit settings it had not checked against the live services: `per_company` 5, which SEC rejects with HTTP 400, and no age limit on filings, so the first successful run sent 33 alerts, 32 of them about filings up to a year old. Claude had also expected the first live run to show the NVDA move; it showed "0 new" because Stooq returned a bot-check page that the kit read as an empty price list. I found all three by checking Muse's results against what I knew had happened that week (NVDA fell 14% on 2026-11-20). They are fixed in `0d6c406` and `d77dbd5` and described in METRICS.md, Part 1.
