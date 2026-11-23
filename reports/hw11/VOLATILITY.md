# HW11 Part 2 — threshold evidence (daily volatility)

Data: Yahoo Finance chart API, adjusted daily close, `range=1y&interval=1d`,
2025-11-21 to 2026-11-20 (250 daily returns per ticker). Pulled 2026-11-22.
Return = close[t] / close[t-1] - 1. sigma = sample standard deviation of daily returns.

| Ticker | CIK | sigma | median abs move | p95 | p99 | max | days >= 5% |
|---|---|---|---|---|---|---|---|
| KO   | 0000021344 | 1.19% | 0.68% | 2.33% | 3.86% | 5.00%  | 0  |
| KR   | 0000056873 | 1.90% | 1.22% | 3.65% | 5.27% | 8.43%  | 3  |
| NVDA | 0001045810 | 2.60% | 1.55% | 4.57% | 8.74% | 14.01% | 10 |
| TSLA | 0001318605 | 2.91% | 1.77% | 5.51% | 8.46% | 14.52% | 17 |

A single 5% rule would never alert on KO and would alert on TSLA 17 times a year.

Rule: digest at about 1.5 sigma, notify at about 3 sigma, rounded to 0.5%.

| Ticker | digest floor (`threshold_pct`) | notify line | notify days last year | digest days last year |
|---|---|---|---|---|
| KO   | 2.0% | 3.5% | 4 | 19 |
| KR   | 3.0% | 5.5% | 2 | 24 |
| NVDA | 4.0% | 8.0% | 3 | 25 |
| TSLA | 4.5% | 9.0% | 2 | 22 |

Result: each ticker alerts about once a quarter and lands in the digest about every two weeks.

Design note: KR was first grouped with KO as a "steady" stock. Its sigma (1.90%) is
1.6x KO's, so the two-group design was dropped for per-ticker thresholds.

Fixture companies (fictional) use the same tiers: GRVL and HRVT on the KO tier (2.0 / 3.5),
VLTA on the NVDA tier (4.0 / 8.0).
