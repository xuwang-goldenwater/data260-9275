"""
HW8 self-check (smoke test) -> reports/hw08/verification.json

    make verify-hw08

Needs Docker with the HW8 compose stack up (docker compose up -d). Does not
need Ollama and does not start the agents: the live checks are the Part 1
request/response service; Parts 2-3 are checked with in-process unit checks
of the agent code plus the saved evidence in reports/hw08/raw/.

  Repo    no uncommitted changes outside reports/
  Docker  kafka, worker and api containers running; 7 s9275 topics, s9275_tasks has 2 partitions
  Part 1  CREATE -> GET round trip through Kafka; error cases (missing field,
          unknown id, unknown operation) return success false; correlation_id
          echoed every time; same round trip through FastAPI on 8275
  Part 2  saved final message: status + answer, correlation_id kept, 3-hop trace;
          Reviewer rule rejects a draft that copies the plan
  Part 3  idempotency store survives a reload; poison message uses exactly 3
          attempts; saved evidence for all four failure rows (before vs after)

Temporary data: one recall notice in the worker's in-memory dict, and a
processed-id file in a temporary directory. No application file is changed.
"""
import csv
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code" / "kafka_app"))
sys.path.insert(0, str(ROOT / "code" / "kafka_agents"))

HW8 = ROOT / "reports" / "hw08"
RAW = HW8 / "raw"
SID4, SEED, VERIFY_SEED = 9275, 9275, 269275
PREFIX = f"s{SID4}"
PORT_BASE = 8000 + SID4 % 900
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


# ---------------------------------------------------------------- Docker

def docker():
    names = (run("docker", "ps", "--format", "{{.Names}}") or "").split()
    for c in ("s9275-kafka", "s9275-worker", "s9275-api"):
        check(f"Docker: container {c} running", c in names, names)
    desc = run("docker", "exec", "s9275-kafka", "/opt/kafka/bin/kafka-topics.sh",
               "--describe", "--bootstrap-server", "localhost:9092") or ""
    parts = {}
    for line in desc.splitlines():
        if line.startswith("Topic:") and "PartitionCount" in line:
            fields = dict(f.split(": ", 1) for f in line.split("\t") if ": " in f)
            parts[fields["Topic"]] = int(fields["PartitionCount"])
    wanted = [f"{PREFIX}_{t}" for t in ("recall_notice_requests", "recall_notice_responses",
                                        "inbox", "tasks", "drafts", "final", "dead_letter")]
    missing = [t for t in wanted if t not in parts]
    check("Kafka: all 7 s9275 topics exist", not missing, missing or sorted(parts))
    check("Kafka: s9275_tasks has 2 partitions", parts.get(f"{PREFIX}_tasks") == 2,
          parts.get(f"{PREFIX}_tasks"))


# ---------------------------------------------------------------- Part 1

NOTICE = {"productName": "Verify Oat Bar 6-pack", "recallingFirm": "Verify Foods",
          "submitterEmail": "qa@verifyfoods.com", "category": "Foreign Material",
          "description": "Lot VF100 may contain small metal fragments from a damaged sieve.",
          "agreedToTerms": True}


class KafkaClient:
    def __init__(self):
        from confluent_kafka import Consumer, Producer
        from recall_service import REQUEST_TOPIC, RESPONSE_TOPIC
        self.req, self.resp = REQUEST_TOPIC, RESPONSE_TOPIC
        self.producer = Producer({"bootstrap.servers": "localhost:9092"})
        self.consumer = Consumer({"bootstrap.servers": "localhost:9092",
                                  "group.id": f"s9275_verify_{uuid.uuid4().hex[:8]}",
                                  "auto.offset.reset": "latest", "enable.auto.commit": True})
        self.consumer.subscribe([self.resp])
        deadline = time.time() + 15
        while not self.consumer.assignment() and time.time() < deadline:
            self.consumer.poll(0.2)

    def call(self, operation, data):
        cid = f"verify-{uuid.uuid4()}"
        self.producer.produce(self.req, key=cid, value=json.dumps(
            {"correlation_id": cid, "reply_to": self.resp, "operation": operation, "data": data}))
        self.producer.flush(10)
        deadline = time.time() + 15
        while time.time() < deadline:
            msg = self.consumer.poll(0.5)
            if msg is not None and not msg.error():
                r = json.loads(msg.value())
                if r.get("correlation_id") == cid:
                    return cid, r
        return cid, None


def part1():
    client = KafkaClient()
    cid, created = client.call("CREATE_RECALL_NOTICE", NOTICE)
    ok = bool(created and created.get("success") and created.get("recall_notice_id"))
    check("P1 Kafka CREATE_RECALL_NOTICE -> success + recall_notice_id", ok, created)
    check("P1 CREATE response echoes correlation_id", created and created["correlation_id"] == cid)
    if ok:
        nid = created["recall_notice_id"]
        cid2, got = client.call("GET_RECALL_NOTICE", {"recall_notice_id": nid})
        rec = (got or {}).get("recall_notice", {})
        check("P1 Kafka GET_RECALL_NOTICE round-trips the created record",
              got and got.get("success") and rec.get("recall_notice_id") == nid
              and rec.get("productName") == NOTICE["productName"], got and got.get("success"))
        check("P1 GET response echoes correlation_id", got and got["correlation_id"] == cid2)
    for label, op, data in [
        ("missing productName", "CREATE_RECALL_NOTICE",
         {k: v for k, v in NOTICE.items() if k != "productName"}),
        ("unknown recall_notice_id", "GET_RECALL_NOTICE", {"recall_notice_id": "no-such-id"}),
        ("unknown operation", "DELETE_RECALL_NOTICE", {}),
    ]:
        c, r = client.call(op, data)
        check(f"P1 error case ({label}) -> success false + error + same correlation_id",
              r is not None and r.get("success") is False and r.get("error")
              and r.get("correlation_id") == c, r and r.get("error"))
    client.consumer.close()

    # Same round trip through the FastAPI wrapper.
    api_cid = f"verify-api-{uuid.uuid4().hex[:8]}"
    req = urllib.request.Request(f"http://127.0.0.1:{PORT_BASE}/recall-notices",
                                 data=json.dumps(NOTICE).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-Correlation-ID": api_cid})
    body = json.loads(urllib.request.urlopen(req, timeout=20).read())
    check(f"P1 FastAPI POST /recall-notices on {PORT_BASE} -> success, caller's correlation_id kept",
          body.get("success") and body.get("correlation_id") == api_cid, body)
    if body.get("success"):
        nid = body["recall_notice_id"]
        got = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{PORT_BASE}/recall-notices/{nid}", timeout=20).read())
        check("P1 FastAPI GET /recall-notices/{id} returns the record",
              got.get("success") and got["recall_notice"]["recall_notice_id"] == nid)


# ---------------------------------------------------------------- Part 2

def part2():
    final = json.loads((RAW / "part2_final.json").read_text())
    check("P2 saved final message has status and answer",
          final.get("status") in ("approved", "rejected") and len(final.get("answer", "")) > 0,
          final.get("status"))
    journey = (RAW / "part2_journey.log").read_text()
    check("P2 correlation_id preserved end to end (saved run)",
          "correlation_id preserved end to end: True" in journey
          and final["correlation_id"] in journey)
    agents = [t["agent"] for t in final.get("trace", [])]
    check("P2 trace shows planner -> writer -> reviewer",
          len(agents) == 3 and agents[0] == "planner" and agents[1].startswith("writer")
          and agents[2] == "reviewer", agents)
    from reviewer import rule_check
    plan = final["plan"]
    check("P2 Reviewer rule rejects a draft that copies the plan",
          rule_check("\n".join(f"{i}. {s}" for i, s in enumerate(plan, 1)), plan) is not None)
    check("P2 Reviewer rule accepts the saved real answer",
          rule_check(final["answer"], plan) is None)


# ---------------------------------------------------------------- Part 3

def part3():
    import reliability
    reliability.STATE_DIR = Path(tempfile.mkdtemp(prefix="hw08_verify_"))   # temp, not var/
    reliability.BACKOFF_S = 0
    store = reliability.ProcessedStore("verify")
    store.mark("cid-1")
    check("P3 idempotency: processed id still known after reload",
          reliability.ProcessedStore("verify").seen("cid-1")
          and not reliability.ProcessedStore("verify").seen("cid-2"))
    attempts = []
    ok, err, used = reliability.run_with_retries(lambda m: m["question"], {"plan": []},
                                                 on_retry=lambda n, e: attempts.append(n))
    check("P3 poison message: 3 attempts, then reported as failed",
          not ok and used == 3 and attempts == [1, 2, 3] and "KeyError" in err, err)

    def drafts(log, cid):
        for line in (RAW / log).read_text().splitlines():
            if f"cid={cid} " in line and "drafts in" in line:
                return int(line.rsplit(":", 1)[1])
        return None

    check("P3 duplicate: 2 drafts before fix, 1 after",
          (drafts("p3_dup_check.log", "dup-0c594693"), drafts("p3_dup_check.log", "dup-9bd1743b"))
          == (2, 1))
    check("P3 consumer death: 0 drafts before fix (lost), 1 after (redelivered)",
          (drafts("p3_kill_before_offsets.log", "kill-a0c7ae0b"),
           drafts("p3_kill_after_offsets.log", "kill-e2ca57a0")) == (0, 1))
    dlq = json.loads((RAW / "dead_letter.json").read_text())
    check("P3 poison: message in s9275_dead_letter with attempts 3 and the error",
          any(r.get("attempts") == 3 and "KeyError" in r.get("error", "") for r in dlq), len(dlq))
    check("P3 poison: the message behind it was processed (1 draft)",
          drafts("p3_poison_dlq.log", "after-poison-542fb13e") == 1)

    nokey = json.loads((RAW / "ordering_nokey_summary.json").read_text())
    keyed = json.loads((RAW / "ordering_keyed_summary.json").read_text())
    check("P3 ordering: both runs used VERIFY_SEED and processed 20 messages",
          nokey["verify_seed"] == keyed["verify_seed"] == VERIFY_SEED
          and nokey["processed"] == keyed["processed"] == 20)
    check("P3 ordering without key: recalls split across partitions, order violated",
          all(len(r["partitions"]) == 2 for r in nokey["recalls"].values())
          and nokey["total_violations"] > 0, nokey["total_violations"])
    check("P3 ordering with key: one partition per recall, 0 violations",
          all(len(r["partitions"]) == 1 for r in keyed["recalls"].values())
          and keyed["total_violations"] == 0)
    rows = list(csv.DictReader((RAW / "ordering_keyed.csv").open()))
    check("P3 ordering keyed CSV: 20 rows, both Writers used",
          len(rows) == 20 and {r["writer"] for r in rows} == {"w1", "w2"})


def main():
    print(f"Xu Wang | DATA 260 HW8 self-check | {datetime.now():%Y-%m-%d %H:%M:%S}")
    dirty = [line for line in (git("status", "--porcelain") or "").splitlines()
             if line[3:] and not line[3:].startswith("reports/")]
    check("Repo: no uncommitted changes outside reports/", not dirty, dirty[:5])
    for name, fn in [("Docker", docker), ("P1", part1), ("P2", part2), ("P3", part3)]:
        safe(name, fn)
    passed = sum(c["passed"] for c in checks)
    result = {"student": "Xu Wang", "homework": "HW8", "sid4": SID4,
              "run_at": datetime.now().isoformat(timespec="seconds"),
              "commit": git("rev-parse", "--short", "HEAD"),
              "model": "qwen2.5:3b (Ollama, temperature 0, seed 9275) - Part 2 agents",
              "kafka": "apache/kafka:3.8.0, 1 broker, KRaft",
              "seed": SEED, "verify_seed": VERIFY_SEED,
              "passed": passed, "failed": len(checks) - passed, "checks": checks}
    (HW8 / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{passed} passed, {len(checks) - passed} failed -> reports/hw08/verification.json")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
