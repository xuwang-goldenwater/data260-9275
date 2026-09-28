| Page size | Version | SQL stmts/req (total / list) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| 10 | naive | 13 / 11 | 10.21 | 12.33 | 15.91 |
| 10 | fixed | 3 / 1 | 9.6 | 12.94 | 14.52 |
| 50 | naive | 53 / 51 | 19.33 | 20.98 | 22.33 |
| 50 | fixed | 3 / 1 | 10.53 | 12.52 | 23.29 |
| 200 | naive | 203 / 201 | 52.51 | 57.3 | 67.47 |
| 200 | fixed | 3 / 1 | 12.76 | 14.93 | 15.65 |

Speed-up (naive p50 / fixed p50): page 10 = 1.06x, page 50 = 1.84x, page 200 = 4.12x
