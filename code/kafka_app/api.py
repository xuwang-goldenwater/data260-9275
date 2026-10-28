"""
DATA 260 - HW8 Part 1: FastAPI wrapper over the Kafka request/response service.

The API never touches the entity store. Each HTTP call becomes one Kafka
request on s9275_recall_notice_requests; the API then waits for the response
with the same correlation_id on s9275_recall_notice_responses.

How waiting works:
  - a background thread consumes the responses topic
  - PENDING maps correlation_id -> asyncio Future for each in-flight request
  - when a response arrives, the thread resolves the matching Future
  - a response nobody is waiting for (late, or for another client) is logged and ignored

correlation_id: the caller may send its own in the X-Correlation-ID header;
the API forwards it unchanged. Only when it is missing does the API create one.

Run:  python code/kafka_app/api.py         (on the Mac)
      docker compose up -d api             (in Docker)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from confluent_kafka import Consumer, Producer
from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool

from recall_service import REQUEST_TOPIC, RESPONSE_TOPIC

SID4 = 9275
PORT_BASE = 8000 + SID4 % 900          # 8275
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
BIND_HOST = os.getenv("BIND_HOST", "127.0.0.1")   # 0.0.0.0 inside the container
TIMEOUT_S = 10.0

PENDING: Dict[str, "asyncio.Future"] = {}
LOOP: Optional[asyncio.AbstractEventLoop] = None
producer = Producer({"bootstrap.servers": BOOTSTRAP})
stop_event = threading.Event()
ready_event = threading.Event()


def log(stage: str, text: str) -> None:
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{now} [api]    {stage:<9} {text}", flush=True)


def response_listener() -> None:
    """Background thread: read every response and hand it to the waiting request."""
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        # Own group per API process, so it sees all responses and never
        # competes with another API instance for them.
        "group.id": f"s9275_api_{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([RESPONSE_TOPIC],
                       on_assign=lambda c, parts: ready_event.set())
    while not stop_event.is_set():
        msg = consumer.poll(0.5)
        if msg is None or msg.error():
            continue
        try:
            response = json.loads(msg.value())
        except ValueError:
            continue
        cid = response.get("correlation_id")
        fut = PENDING.get(cid)
        if fut is None:
            log("IGNORED", f"no waiter for cid={cid}")
            continue
        log("RECEIVED", f"topic={RESPONSE_TOPIC} {json.dumps(response)}")
        LOOP.call_soon_threadsafe(lambda f=fut, r=response: f.done() or f.set_result(r))
    consumer.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LOOP
    LOOP = asyncio.get_running_loop()
    thread = threading.Thread(target=response_listener, daemon=True)
    thread.start()
    # Wait until the response consumer has its partition, otherwise with
    # offset reset "latest" a very fast first response could be missed.
    await run_in_threadpool(ready_event.wait, 15)
    log("READY", f"FastAPI server started at http://127.0.0.1:{PORT_BASE} "
                 f"(kafka={BOOTSTRAP})")
    yield
    stop_event.set()
    thread.join(timeout=3)


app = FastAPI(title="s9275 Recall Notice API over Kafka", lifespan=lifespan)


async def call_worker(operation: str, data: Dict[str, Any], cid: Optional[str]) -> Dict[str, Any]:
    """Send one request to Kafka and wait for its response."""
    cid = cid or str(uuid.uuid4())
    request = {"correlation_id": cid, "reply_to": RESPONSE_TOPIC,
               "operation": operation, "data": data}
    fut = LOOP.create_future()
    PENDING[cid] = fut
    try:
        log("SENT", f"topic={REQUEST_TOPIC} {json.dumps(request)}")
        producer.produce(REQUEST_TOPIC, key=cid, value=json.dumps(request))
        await run_in_threadpool(producer.flush, 5)
        response = await asyncio.wait_for(fut, TIMEOUT_S)
    except asyncio.TimeoutError:
        log("TIMEOUT", f"cid={cid} no response after {TIMEOUT_S}s")
        raise HTTPException(504, detail={"correlation_id": cid,
                                         "error": "No response from worker"})
    finally:
        PENDING.pop(cid, None)
    log("RETURNED", f"cid={cid} success={response.get('success')} -> HTTP caller")
    return response


@app.get("/health")
async def health():
    return {"ok": True, "port": PORT_BASE, "kafka": BOOTSTRAP}


@app.post("/recall-notices")
async def create_notice(data: Dict[str, Any],
                        x_correlation_id: Optional[str] = Header(default=None)):
    return await call_worker("CREATE_RECALL_NOTICE", data, x_correlation_id)


@app.get("/recall-notices/{recall_notice_id}")
async def get_notice(recall_notice_id: str,
                     x_correlation_id: Optional[str] = Header(default=None)):
    return await call_worker("GET_RECALL_NOTICE",
                             {"recall_notice_id": recall_notice_id}, x_correlation_id)


@app.post("/requests")
async def raw_request(body: Dict[str, Any]):
    """Pass any operation through unchanged - used to show 'Unknown operation'."""
    return await call_worker(str(body.get("operation")), body.get("data") or {},
                             body.get("correlation_id"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=BIND_HOST, port=PORT_BASE)
