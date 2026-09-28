"""
HW4 Part 3 steps 4-7 - measure the naive (N+1) and fixed (JOIN) list endpoints.

    make run-hw04          # terminal 1: the API on 8275
    make bench-n1          # terminal 2: this script

Design
- Real HTTP against the running server, logged in with the demo user.
- 3 page sizes x 2 versions x 30 measured requests = 180 rows.
- 5 warm-up requests per (size, version) first, not recorded: the first
  requests pay for connection setup and MySQL's cold buffer pool.
- Paired and interleaved: repetition r picks one random page (seeded with
  SEED) and sends naive and fixed for that same page back to back, in an
  order that alternates each repetition. Both versions therefore see the same
  rows and the same machine conditions; drift over time hits both equally.
- For every request we keep the client latency (perf_counter around the HTTP
  call), the server's own time (X-Server-Time-Ms) and the statement counts
  from the server (X-SQL-Total = everything, X-SQL-List = the list work only;
  the difference is the 2 statements of the session check).
- Every naive/fixed pair is compared: the JSON items must be identical.

Output (reports/hw04/raw/)
  n1_requests.csv    one row per measured request (180 rows)
  n1_summary.json    p50/p95/p99, statements, speed-up per page size
  n1_table.md        the METRICS.md table, ready to paste
"""
import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
import config  # noqa: E402

BASE = f"http://localhost:{config.PORT_BASE}"
RAW_DIR = ROOT / "reports" / "hw04" / "raw"
PAGE_SIZES = [10, 50, 200]
VERSIONS = ["naive", "fixed"]
REPS = 30
WARMUP = 5
TOTAL_ROWS = 5000


def percentile(values, p):
    """Linear interpolation between closest ranks (same as numpy's default)."""
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def call(client, version, page_size, page):
    started = time.perf_counter()
    r = client.get(f"/api/notices/{version}", params={"page": page, "page_size": page_size})
    latency_ms = (time.perf_counter() - started) * 1000.0
    r.raise_for_status()
    return r, latency_ms


def main():
    rng = random.Random(config.SEED)
    started_at = datetime.now().isoformat(timespec="seconds")
    print(f"===== bench-n1 {started_at}  base={BASE}  reps={REPS}  warmup={WARMUP} =====")

    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        client.post("/api/auth/login", json={"email": config.DEMO_EMAIL,
                                             "password": config.DEMO_PASSWORD}).raise_for_status()
        health = client.get("/api/health").json()
        print(f"server: {health}")

        for size in PAGE_SIZES:
            for version in VERSIONS:
                for _ in range(WARMUP):
                    call(client, version, size, 1)

        rows, seq = [], 0
        for rep in range(1, REPS + 1):
            for size in PAGE_SIZES:
                page = rng.randint(1, TOTAL_ROWS // size)
                order = VERSIONS if rep % 2 else list(reversed(VERSIONS))
                bodies = {}
                for version in order:
                    seq += 1
                    r, latency_ms = call(client, version, size, page)
                    body = r.json()
                    bodies[version] = body["items"]
                    rows.append({
                        "seq": seq, "rep": rep, "page_size": size, "version": version,
                        "page": page, "status": r.status_code,
                        "rows_returned": len(body["items"]),
                        "sql_total": int(r.headers["X-SQL-Total"]),
                        "sql_list": int(r.headers["X-SQL-List"]),
                        "client_ms": round(latency_ms, 3),
                        "server_ms": float(r.headers["X-Server-Time-Ms"]),
                        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                    })
                same = bodies["naive"] == bodies["fixed"]
                for row in rows[-2:]:
                    row["same_items_as_other_version"] = same
            print(f"rep {rep:2d}/{REPS} done")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAW_DIR / "n1_requests.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = {"started_at": started_at, "base": BASE, "reps": REPS, "warmup": WARMUP,
               "seed": config.SEED, "requests": len(rows), "groups": []}
    for size in PAGE_SIZES:
        for version in VERSIONS:
            group = [r for r in rows if r["page_size"] == size and r["version"] == version]
            client_ms = [r["client_ms"] for r in group]
            server_ms = [r["server_ms"] for r in group]
            summary["groups"].append({
                "page_size": size, "version": version, "n": len(group),
                "sql_total_per_req": sorted({r["sql_total"] for r in group}),
                "sql_list_per_req": sorted({r["sql_list"] for r in group}),
                "p50_ms": round(percentile(client_ms, 50), 2),
                "p95_ms": round(percentile(client_ms, 95), 2),
                "p99_ms": round(percentile(client_ms, 99), 2),
                "server_p50_ms": round(percentile(server_ms, 50), 2),
                "all_items_identical": all(r["same_items_as_other_version"] for r in group),
            })
    speedups = {}
    for size in PAGE_SIZES:
        g = {x["version"]: x for x in summary["groups"] if x["page_size"] == size}
        speedups[size] = round(g["naive"]["p50_ms"] / g["fixed"]["p50_ms"], 2)
    summary["speedup_p50_naive_over_fixed"] = speedups
    (RAW_DIR / "n1_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = ["| Page size | Version | SQL stmts/req (total / list) | p50 (ms) | p95 (ms) | p99 (ms) |",
             "|---|---|---|---|---|---|"]
    for g in summary["groups"]:
        stmts = f"{'/'.join(map(str, g['sql_total_per_req']))} / {'/'.join(map(str, g['sql_list_per_req']))}"
        lines.append(f"| {g['page_size']} | {g['version']} | {stmts} | "
                     f"{g['p50_ms']} | {g['p95_ms']} | {g['p99_ms']} |")
    lines.append("")
    lines.append("Speed-up (naive p50 / fixed p50): " +
                 ", ".join(f"page {s} = {v}x" for s, v in speedups.items()))
    table = "\n".join(lines)
    (RAW_DIR / "n1_table.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    print(f"wrote {len(rows)} rows to {RAW_DIR / 'n1_requests.csv'}")


if __name__ == "__main__":
    main()
