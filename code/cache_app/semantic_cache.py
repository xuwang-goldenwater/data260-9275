"""
DATA 260 HW9 Part 2 - semantic response cache in front of the HW8 agent pipeline.

    ask(question)
      1. embed the question (MiniLM, 384 numbers, unit length)
      2. KNN 1 in the Redis vector index, cosine
      3. similarity >= threshold  -> HIT:  return the stored final answer,
                                          the HW8 agents do not run
         otherwise                -> MISS: look up the recall record (facts),
                                          send the question through
                                          Planner -> Writer -> Reviewer (Kafka),
                                          store the answer, return it

Each cache entry is one Redis hash  s9275:semcache:<sha1 of the query>  with
    query, embedding, answer, notice_id, data_version, created_at
data_version is the version of the recall record the answer was built from
(s9275:ver:recall_notice:<id>, used in Part 3.5).

Needs: Redis (docker compose up -d redis), MySQL, Kafka + planner/writer/reviewer
running (only for misses), Ollama.

    python code/cache_app/semantic_cache.py "How many units were affected by recall F-0001-2025?"
    python code/cache_app/semantic_cache.py --reset      # drop the index and every entry
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import redis
from redis.commands.search.field import TagField, TextField, VectorField
try:                                   # redis-py >= 6
    from redis.commands.search.index_definition import IndexDefinition, IndexType
except ImportError:                    # redis-py 5.x
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT / "code" / "kafka_agents"))
sys.path.insert(0, str(ROOT / "code" / "observability"))
from tracing import new_trace_id, record_queue_wait, span  # noqa: E402  HW10 Part 4

PREFIX = "s9275"
ENTRY_PREFIX = f"{PREFIX}:semcache:"
INDEX_NAME = f"{PREFIX}:semcache_idx"
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"   # same model as HW3/HW4
DIM = 384
DEFAULT_THRESHOLD = 0.85
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
VERSION_CHECK = os.getenv("VERSION_CHECK", "1") == "1"        # Part 3.5 switch
RECALL_GUARD = os.getenv("RECALL_GUARD", "1") == "1"          # Part 3.4 shipped config
CACHE_STORE = os.getenv("CACHE_STORE", "1") == "1"            # HW10 4.3: 0 = never write answers
AGENT_TIMEOUT_S = float(os.getenv("AGENT_TIMEOUT_S", "240"))   # HW10 failed-trace demo uses a short one
RECALL_NUMBER = re.compile(r"\bF-\d{4}-\d{4}\b", re.IGNORECASE)
QUERY_LOG = Path(os.getenv("CACHE_QUERY_LOG", ROOT / "reports/hw09/raw/part2_queries.jsonl"))

log = logging.getLogger("semantic_cache")


def recall_guard_ok(incoming: str, cached: str) -> bool:
    """Part 3.4: a hit may only reuse an answer about the SAME recall number.
    The sweep showed MiniLM scores 'units of F-0001-2025' vs 'units of F-0002-2021'
    at 0.97, above real paraphrases, so the threshold cannot separate them.
    Both questions without a recall number -> no constraint (general questions)."""
    a = {m.upper() for m in RECALL_NUMBER.findall(incoming)}
    b = {m.upper() for m in RECALL_NUMBER.findall(cached)}
    return a == b


def version_key(notice_id) -> str:
    return f"{PREFIX}:ver:recall_notice:{notice_id}"


class Embedder:
    """MiniLM on the CPU (HW4 lesson: on MPS it fought Ollama for GPU memory)."""

    def __init__(self, name: str = EMBED_MODEL_NAME):
        # The model is already in the local Hugging Face cache (HW3/HW4): load it
        # without ~30 HTTP checks against huggingface.co on every start.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(name, device="cpu")

    def __call__(self, text: str) -> np.ndarray:
        return self.model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0].astype(np.float32)


class SemanticCache:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD, redis_url: str = REDIS_URL,
                 recall_guard: bool = RECALL_GUARD):
        self.threshold = threshold
        self.recall_guard = recall_guard
        self.r = redis.Redis.from_url(redis_url, decode_responses=True)
        self.embed = Embedder()
        self._repo = None        # MySQL, opened on first miss
        self._producer = None    # Kafka, opened on first miss
        self._consumer = None
        self.ensure_index()

    # ---- Redis vector index ------------------------------------------------
    def ensure_index(self) -> None:
        try:
            self.r.ft(INDEX_NAME).info()
            return                                   # already there
        except redis.ResponseError:
            pass
        schema = (
            TextField("query"),
            TagField("notice_id"),
            VectorField("embedding", "FLAT",
                        {"TYPE": "FLOAT32", "DIM": DIM, "DISTANCE_METRIC": "COSINE"}),
        )
        self.r.ft(INDEX_NAME).create_index(
            schema, definition=IndexDefinition(prefix=[ENTRY_PREFIX], index_type=IndexType.HASH))
        log.info("created index %s on %s*", INDEX_NAME, ENTRY_PREFIX)

    def reset(self) -> None:
        """Drop the index and all entries (DD = delete documents too)."""
        try:
            self.r.ft(INDEX_NAME).dropindex(delete_documents=True)
        except redis.ResponseError:
            pass
        self.ensure_index()

    def lookup(self, vec: np.ndarray) -> Optional[dict]:
        """Nearest cached query. Redis returns cosine DISTANCE; similarity = 1 - distance."""
        q = (Query("*=>[KNN 1 @embedding $vec AS dist]")
             .return_fields("query", "answer", "notice_id", "data_version", "dist")
             .sort_by("dist").dialect(2))
        res = self.r.ft(INDEX_NAME).search(q, query_params={"vec": vec.tobytes()})
        if not res.docs:
            return None
        d = res.docs[0]
        return {"key": d.id, "query": d.query, "answer": d.answer,
                "notice_id": d.notice_id, "data_version": int(d.data_version),
                "similarity": 1.0 - float(d.dist)}

    def store(self, question: str, vec: np.ndarray, answer: str,
              notice_id: Optional[int], data_version: int) -> str:
        key = ENTRY_PREFIX + hashlib.sha1(question.encode()).hexdigest()[:16]
        self.r.hset(key, mapping={
            "query": question, "embedding": vec.tobytes(), "answer": answer,
            "notice_id": "" if notice_id is None else str(notice_id),
            "data_version": data_version,
            "created_at": datetime.now().isoformat(timespec="seconds")})
        return key

    def current_version(self, notice_id) -> int:
        if notice_id in (None, ""):
            return 0
        return int(self.r.get(version_key(notice_id)) or 0)

    # ---- the miss path: facts + HW8 agents -----------------------------------
    def facts_for(self, question: str) -> tuple[Optional[dict], Optional[int]]:
        """Recall record named in the question, flattened for the Writer prompt.
        No recall number -> (None, None): the message has no 'facts', HW8 behaviour."""
        m = RECALL_NUMBER.search(question)
        if not m:
            return None, None
        number = m.group(0).upper()
        if self._repo is None:
            from domain_tools import MySQLRepo
            self._repo = MySQLRepo()
        n = self._repo.get(number)
        if n is None:
            return {"not_found": number}, None
        facts = {"recall_number": n["recall_number"], "product_name": n["product_name"],
                 "category": n["category"], "recall_date": n["recall_date"],
                 "units_affected": n["units_affected"],
                 "firm_name": n["firm"]["name"], "firm_state": n["firm"]["state"]}
        return facts, n["id"]

    def run_agent(self, question: str, facts: Optional[dict], trace_id: Optional[str] = None,
                  extra: Optional[dict] = None) -> dict:
        """Send to s9275_inbox, wait for the same correlation_id on s9275_final.
        HW10: correlation_id IS the trace_id created in ask(); extra carries test
        fields such as {"fail_at": "writer"} (Part 4.2 failed trace)."""
        from confluent_kafka import Consumer
        from common import BOOTSTRAP, FINAL, INBOX, make_producer, send
        if self._consumer is None:          # one consumer for the whole run, joined once
            self._consumer = Consumer({"bootstrap.servers": BOOTSTRAP,
                                       "group.id": f"{PREFIX}_cache_{uuid.uuid4().hex[:8]}",
                                       "auto.offset.reset": "latest",
                                       "enable.auto.commit": True,
                                       # HW10: a caller may pause between requests (the latency
                                       # run waits for the evaluator); without this the idle
                                       # consumer is kicked out after 300 s (MAXPOLL).
                                       "max.poll.interval.ms": 3600000})
            self._consumer.subscribe([FINAL])
            joined_by = time.time() + 30          # HW10: never wait forever for Kafka
            while not self._consumer.assignment():
                if time.time() > joined_by:
                    self._consumer.close()
                    self._consumer = None
                    raise ConnectionError(f"no partition of {FINAL} assigned in 30s - is Kafka up?")
                self._consumer.poll(0.2)
            self._producer = make_producer()
        cid = trace_id or new_trace_id()       # HW9 threshold_sweep.py calls without one
        message = {"correlation_id": cid, "question": question, **(extra or {})}
        if facts is not None:
            message["facts"] = facts
        send(self._producer, INBOX, message)
        deadline = time.time() + AGENT_TIMEOUT_S
        while time.time() < deadline:
            msg = self._consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            final = json.loads(msg.value())
            if final.get("correlation_id") == cid:
                record_queue_wait(cid, "final", msg)      # hop 4: s9275_final -> gateway
                return final
        raise TimeoutError(f"no answer for {cid} in {AGENT_TIMEOUT_S}s - are the 3 agents running?")

    # ---- the ingress ---------------------------------------------------------
    def ask(self, question: str, trace_id: Optional[str] = None,
            extra: Optional[dict] = None) -> dict:
        """HW10: the trace_id is created here, BEFORE the cache lookup, so hits
        and misses both have one; on a miss it becomes the Kafka correlation_id."""
        trace_id = trace_id or new_trace_id()
        with span(trace_id, "gateway", question=question) as g:   # = end-to-end span
            out = self._ask(question, trace_id, extra)
            g["cache"] = "hit" if out["is_cached"] else "miss"
            # A Reviewer rejection is an answer outcome, not a system error: the request
            # completed. Errors are exceptions/timeouts (span() records those itself).
            g["outcome"] = "cached" if out["is_cached"] else out.get("status")
            return out

    def _ask(self, question: str, trace_id: str, extra: Optional[dict]) -> dict:
        t0 = time.perf_counter()
        with span(trace_id, "cache_lookup") as c:
            vec = self.embed(question)
            t_embed = time.perf_counter()
            best = self.lookup(vec)
            t_search = time.perf_counter()
            sim = best["similarity"] if best else None
            c["similarity"] = None if sim is None else round(sim, 4)
            timings = {"embed_ms": (t_embed - t0) * 1000, "search_ms": (t_search - t_embed) * 1000}

            if best and sim >= self.threshold and self.recall_guard \
                    and not recall_guard_ok(question, best["query"]):
                log.info("CACHE GUARD sim=%.4f but recall number differs from %r -> miss",
                         sim, best["query"])
                c["miss_reason"] = "recall_guard"
                best = None                   # not allowed to reuse; fall through to the agents
            hit = None
            if best and sim >= self.threshold:
                stale = VERSION_CHECK and best["data_version"] != self.current_version(best["notice_id"])
                if not stale:
                    hit = best
                else:                         # Part 3.5: record changed after the answer was cached
                    self.r.delete(best["key"])
                    c["miss_reason"] = "stale"
                    log.info("CACHE STALE sim=%.4f  v%s != v%s  -> entry deleted, treated as miss",
                             sim, best["data_version"], self.current_version(best["notice_id"]))
            elif best is not None:
                c["miss_reason"] = "below_threshold"
            elif "miss_reason" not in c:
                c["miss_reason"] = "empty_index"
            c["cache"] = "hit" if hit else "miss"

        if hit:
            total = (time.perf_counter() - t0) * 1000
            log.info("CACHE HIT  sim=%.4f  matched=%r", sim, hit["query"])
            return self._result(question, hit["answer"], True, sim, total, timings, trace_id,
                                matched=hit["query"], notice_id=hit["notice_id"])

        log.info("CACHE MISS best_sim=%s -> HW8 agent pipeline",
                 "none" if sim is None else f"{sim:.4f}")
        with span(trace_id, "facts_lookup"):
            facts, notice_id = self.facts_for(question)
            version = self.current_version(notice_id)
        t_agent = time.perf_counter()
        final = self.run_agent(question, facts, trace_id, extra)
        timings["agent_ms"] = (time.perf_counter() - t_agent) * 1000
        answer = final.get("answer", "")
        if CACHE_STORE and final.get("status") == "approved":   # never cache a rejected answer
            self.store(question, vec, answer, notice_id, version)
        total = (time.perf_counter() - t0) * 1000
        return self._result(question, answer, False, sim, total, timings, trace_id,
                            notice_id=notice_id, status=final.get("status"))

    def _result(self, question, answer, is_cached, sim, total_ms, timings, trace_id,
                **extra) -> dict:
        out = {"trace_id": trace_id, "question": question, "answer": answer, "is_cached": is_cached,
               "similarity": None if sim is None else round(sim, 4),
               "latency_ms": round(total_ms, 1),
               "timings": {k: round(v, 1) for k, v in timings.items()},
               "threshold": self.threshold, "at": datetime.now().isoformat(timespec="seconds"),
               **extra}
        QUERY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with QUERY_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out) + "\n")
        return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "huggingface_hub", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print("Xu Wang | DATA 260 HW9 Part 2 | semantic cache | PREFIX s9275")
    cache = SemanticCache()
    if sys.argv[1:] == ["--reset"]:
        cache.reset()
        print("index and entries dropped, empty index recreated")
    else:
        q = " ".join(sys.argv[1:]) or "How many units were affected by recall F-0001-2025?"
        print(json.dumps(cache.ask(q), indent=2))
