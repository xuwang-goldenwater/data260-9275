"""
HW9 self-check (smoke test) -> reports/hw09/verification.json

    make verify-hw09

Needs the Redis container (docker compose up -d redis) and MySQL. Does not need
Kafka, Ollama or the agents: live checks are Redis + MySQL; everything that used a
model is checked from the saved evidence in reports/hw09/.

  Repo    no uncommitted changes outside reports/; cache_cases.yaml committed
          before the first sweep result
  Redis   s9275-redis running with the search module; every key starts with s9275:
  Part 1  view_count column; INCR count + sync on the 10th call (temporary key,
          a notice id that does not exist, so no row changes)
  Part 2  vector index (COSINE, 384 dims) and entry fields; nearest neighbour of a
          cached seed is itself (sim ~1.0); demo has >= 10 queries of all 3 kinds,
          hit rate / latency recomputed from the rows
  Part 3  40 labeled cases 10 x 4; sweep summary recomputed from sweep_cases.csv;
          recall guard; cost model choice; stale demo (stale hit, then invalidated)
  Part 4  input files hold only id + question; test records unseen in training /
          validation; lessons.json fields; evaluator spot checks; 4.1 controlled
          revision; 4.2 lesson reuse; 4.4 table recomputed from test.json
"""
import csv
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "cache_app"))
sys.path.insert(0, str(ROOT / "code" / "self_improve"))

HW9 = ROOT / "reports" / "hw09"
RAW = HW9 / "raw"
P4 = HW9 / "part4"
SID4, SEED, VERIFY_SEED = 9275, 9275, 269275
PREFIX = f"s{SID4}"
checks = []


def check(name, ok, detail=""):
    checks.append({"name": name, "passed": bool(ok), "detail": str(detail)})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")
    return bool(ok)


def safe(name, fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"error: {type(exc).__name__}: {str(exc)[:200]}")


def run(*args):
    try:
        return subprocess.check_output(list(args), cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).rstrip("\n")
    except Exception:  # noqa: BLE001
        return None


def git(*args):
    return run("git", *args)


def load(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- repo + Redis

def repo_order():
    def first_commit(path):
        out = git("log", "--diff-filter=A", "--format=%ct %h", "--", path) or ""
        return out.splitlines()[-1].split() if out else None
    labels = first_commit("reports/hw09/cache_cases.yaml")
    sweep = first_commit("reports/hw09/raw/sweep_summary.json")
    check("Repo: cache_cases.yaml committed before the first sweep result",
          labels and sweep and int(labels[0]) <= int(sweep[0])
          and git("merge-base", "--is-ancestor", labels[1], sweep[1]) is not None,
          f"labels {labels and labels[1]}, sweep {sweep and sweep[1]}")
    edits = (git("log", "--format=%h", "--", "reports/hw09/cache_cases.yaml") or "").split()
    check("Repo: cache_cases.yaml never edited after it was committed", len(edits) == 1, edits)


def redis_checks():
    names = (run("docker", "ps", "--format", "{{.Names}}") or "").split()
    check("Docker: container s9275-redis running", "s9275-redis" in names, names)
    import redis
    r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    mods = [m.get("name") for m in r.module_list()]
    check("Redis: search module loaded (vector index support)", "search" in mods, mods)
    keys = list(r.scan_iter(count=1000))
    bad = [k for k in keys if not k.startswith(f"{PREFIX}:")]
    check("Redis: every key starts with s9275:", not bad, f"{len(keys)} keys, bad={bad[:5]}")


# ---------------------------------------------------------------- Part 1

def part1():
    from recall_cache import RecallCache
    from sqlalchemy import text
    cache = RecallCache()
    with cache.Session() as db:
        cols = [r[0] for r in db.execute(text("SHOW COLUMNS FROM recall_notices"))]
    check("P1: recall_notices has view_count", "view_count" in cols)
    temp_id = 99999999                          # no such notice: UPDATE touches 0 rows
    key = f"{PREFIX}:views:recall_notice:{temp_id}"
    cache.redis_client.delete(key)
    counts, synced = [], []
    for _ in range(10):
        counts.append(cache.increment_recall_notice_views(temp_id))
        synced.append(cache.last_synced)
    check("P1: INCR returns 1..10", counts == list(range(1, 11)), counts)
    check("P1: sync to database only on the 10th view", synced == [False] * 9 + [True], synced)
    check("P1: key uses the PREFIX", cache.redis_client.get(key) == "10", key)
    cache.redis_client.delete(key)


# ---------------------------------------------------------------- Part 2

def part2():
    import semantic_cache as sc
    cache = sc.SemanticCache()
    info = cache.r.ft(sc.INDEX_NAME).info()
    attrs = json.dumps(info.get("attributes", []))
    check("P2: vector index uses COSINE, 384 dims", "COSINE" in attrs and "384" in attrs,
          sc.INDEX_NAME)
    keys = list(cache.r.scan_iter(f"{sc.ENTRY_PREFIX}*"))
    fields = set(cache.r.hkeys(keys[0])) if keys else set()
    need = {"query", "embedding", "answer", "notice_id", "data_version", "created_at"}
    check("P2: cache entry stores query, embedding, answer, data-version marker",
          need <= fields, sorted(fields))
    seed = "Which firm issued recall F-0002-2021?"
    best = cache.lookup(cache.embed(seed))
    check("P2: a cached seed's nearest neighbour is itself (sim ~1.0)",
          best and best["query"] == seed and best["similarity"] > 0.999,
          best and round(best["similarity"], 4))
    demo = load(RAW / "part2_demo.json")
    rows = demo["queries"]
    kinds = Counter(r["kind"] for r in rows)
    check("P2: >= 10 queries with duplicates, paraphrases and new ones",
          len(rows) >= 10 and all(kinds[k] for k in ("new", "duplicate", "paraphrase")), kinds)
    check("P2: every response has is_cached, similarity and latency",
          all({"is_cached", "similarity", "latency_ms"} <= set(r) for r in rows))
    hits = [r for r in rows if r["is_cached"]]
    check("P2: saved hit rate matches the rows",
          abs(demo["hit_rate"] - len(hits) / len(rows)) < 1e-9, f"{len(hits)}/{len(rows)}")
    check("P2: duplicates were served from cache", all(
        r["is_cached"] for r in rows if r["kind"] == "duplicate"))


# ---------------------------------------------------------------- Part 3

def part3():
    import yaml
    from semantic_cache import recall_guard_ok
    data = yaml.safe_load((HW9 / "cache_cases.yaml").read_text())
    kinds = Counter(c["kind"] for c in data["cases"])
    check("P3.1: 40 labeled cases, 10 of each kind",
          len(data["cases"]) == 40 and set(kinds.values()) == {10}, dict(kinds))
    summary = load(RAW / "sweep_summary.json")["thresholds"]
    check("P3.2: thresholds 0.75 0.80 0.85 0.90 0.95",
          [s["threshold"] for s in summary] == [0.75, 0.80, 0.85, 0.90, 0.95])
    with (RAW / "sweep_cases.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    ok = True
    for s in summary:
        rs = [r for r in rows if float(r["threshold"]) == s["threshold"]]
        hits = sum(r["outcome"] in ("correct_hit", "FALSE_HIT") for r in rs)
        false = sum(r["outcome"] == "FALSE_HIT" for r in rs)
        lat = sum(float(r["latency_ms"]) for r in rs) / len(rs)
        ok &= (len(rs) == 40 and hits == s["hits"] and false == s["false_hits"]
               and abs(lat - s["mean_latency_ms"]) < 1)
    check("P3.2: summary table recomputed from the 200 case rows", ok, len(rows))
    m03 = next(r for r in rows if r["case"] == "M03" and float(r["threshold"]) == 0.95)
    check("P3.3: M03 is a false hit even at 0.95", m03["outcome"] == "FALSE_HIT",
          f"sim {m03['similarity']} -> {m03['nearest_seed']}")
    check("P3.4: recall guard blocks other recall numbers, allows general questions",
          not recall_guard_ok("Units of F-0002-2021?", "Units of F-0001-2025?")
          and recall_guard_ok("Units of F-0001-2025?", "units of f-0001-2025")
          and recall_guard_ok("How to dispose of recalls?", "How to throw away recalls?"))
    cost = load(RAW / "cost_model.json")
    ch = cost["chosen"]
    check("P3.4: cost model ships 0.90 + recall guard",
          ch["threshold"] == 0.90 and ch["recall_guard"] and ch["false_hits"] == 0,
          f"cost {ch['total_cost']}")
    stale = {s["step"][0]: s for s in load(RAW / "stale_demo.json")["steps"]}
    check("P3.5: stale hit returned the old answer (cache on, check off)",
          stale["3"]["is_cached"] and not stale["3"]["answer_matches_db"])
    check("P3.5: version check invalidated it and the new answer matches the database",
          not stale["4"]["is_cached"] and stale["4"]["answer_matches_db"]
          and stale["5"]["is_cached"])


# ---------------------------------------------------------------- Part 4

def part4():
    from evaluator import evaluate, load_reference
    ref = load_reference()
    splits = {s: load(P4 / f"{s}_data.json") for s in ("training", "validation", "test")}
    check("P4: input files hold only id + question (no expected answers)",
          all(set(it) == {"id", "question"} for v in splits.values() for it in v),
          {k: len(v) for k, v in splits.items()})
    import re
    nums = {s: {n for it in v for n in re.findall(r"F-\d{4}-\d{4}", it["question"]) if n in ref}
            for s, v in splits.items()}
    check("P4: test questions ask about records unseen in training / validation",
          not (nums["test"] & (nums["training"] | nums["validation"])), len(nums["test"]))
    lessons = load(P4 / "lessons.json")
    need = {"lesson_id", "failure_pattern", "correction", "created_at", "use_count"}
    check("P4.2: lessons.json entries have the five required fields",
          lessons and all(need <= set(x) for x in lessons), [x["lesson_id"] for x in lessons])
    check("P4.3: every lesson has a validation decision",
          all(x["status"] in ("kept", "removed") and x["validation"] for x in lessons),
          [(x["lesson_id"], x["status"]) for x in lessons])
    r0 = next(iter(ref.values()))
    spot = [
        evaluate(f"How many units were affected by recall {r0['recall_number']}?",
                 f"{r0['units_affected']} units.", ref)["result"] == "PASS",
        evaluate(f"How many units were affected by recall {r0['recall_number']}?",
                 "123456789 units.", ref)["result"] == "REVISE",
        evaluate("What is the capital of France?", "Paris.", ref)["result"] == "REVISE",
        evaluate("How long should I boil an egg?", "I can only answer questions about grocery "
                 "recall notices. Boil it for 9 minutes.", ref)["result"] == "REVISE",
    ]
    check("P4.1: evaluator spot checks (right value, wrong value, off-domain, decline+answer)",
          all(spot), spot)
    train = {r["id"]: r for r in load(P4 / "results/train.json")["rows"]}
    c = train["train_05"]
    check("P4.1: controlled case REVISE -> feedback -> revised PASS in 2 attempts",
          c["n_attempts"] == 2 and c["attempts"][0]["result"] == "REVISE"
          and c["attempts"][0]["feedback"] and c["final_result"] == "PASS")
    check("P4.1: no question used more than 2 attempts",
          all(r["n_attempts"] <= 2 for r in train.values()))
    val = load(P4 / "results/validate.json")
    reused = [r["id"] for rep in val["report"] for r in rep["after"] if r["lessons_loaded"]]
    check("P4.2: a stored lesson was loaded for a later validation question", reused, reused)
    test = load(P4 / "results/test.json")
    ok = True
    for t in test["table"]:
        rows = test["rows"][t["variant"]]
        ok &= (len(rows) == 12 and t["correct"] == sum(r["final_result"] == "PASS" for r in rows)
               and abs(t["avg_attempts"] - sum(r["n_attempts"] for r in rows) / 12) < 1e-9)
    check("P4.4: four variants, table recomputed from the 12 test rows each", ok,
          [(t["variant"], t["correct"]) for t in test["table"]])
    check("P4.4: Baseline used 1 attempt and no lessons",
          all(r["n_attempts"] == 1 and not r["lessons_loaded"] for r in test["rows"]["Baseline"]))


def main():
    print(f"Xu Wang | DATA 260 HW9 self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    dirty = [line for line in (git("status", "--porcelain") or "").splitlines()
             if line[3:] and not line[3:].startswith("reports/")]
    check("Repo: no uncommitted changes outside reports/", not dirty, dirty[:5])
    for name, fn in [("Repo", repo_order), ("Redis", redis_checks), ("P1", part1),
                     ("P2", part2), ("P3", part3), ("P4", part4)]:
        safe(name, fn)
    passed = sum(c["passed"] for c in checks)
    result = {"student": "Xu Wang", "homework": "HW9", "sid4": SID4,
              "run_at": datetime.now().isoformat(timespec="seconds"),
              "commit": git("rev-parse", "--short", "HEAD"),
              "model": "qwen2.5:3b (Ollama, temperature 0, seed 9275) - HW8 agents + Part 4",
              "embedding": "sentence-transformers/all-MiniLM-L6-v2 on CPU",
              "redis": "redis/redis-stack-server:7.4.0-v1",
              "seed": SEED, "verify_seed": VERIFY_SEED,
              "passed": passed, "failed": len(checks) - passed, "checks": checks}
    (HW9 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{passed} passed, {len(checks) - passed} failed -> reports/hw09/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
