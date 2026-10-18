"""HW6 Part 2: short-term, long-term (summary) and episodic memory on MongoDB.

Collections in s9275_doc (Part 1's recall_notices is untouched):
    messages   {user_id, session_id, role, content, created_at}
    summaries  {user_id, session_id|None, scope: 'session'|'user', text, created_at}
    episodes   {user_id, session_id, fact, importance 0..1, embedding [float], created_at}

One chat turn (chat_turn) does, in this order:
    1 save the user message
    2 short-term window  = the N messages before it in this session
    3 long-term memory   = latest session summary + latest lifetime summary
    4 episodic recall    = top-k stored facts by cosine similarity to the message
    5 build the prompt   primer -> summaries -> window -> current message -> facts
    6 call the model through the HW1 adapter (src/model_client.py)
    7 save the assistant reply
    8 extract up to 3 facts from the user message, embed and store them
    9 every M user messages: refresh the session summary;
      every few session summaries: condense them into the lifetime summary

Step 4 runs before step 8 on purpose: if the current message's own facts were
stored first, they would be retrieved as the "most relevant" memories of
themselves and push older facts out of the top-k.

Retrieval is the HW3/HW4 RAG idea: L2-normalised MiniLM vectors, so the dot
product is the cosine. Here the "documents" are facts about the user.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pymongo import ASCENDING, DESCENDING

import config
import db
import token_count

sys.path.insert(0, str(config.ROOT / "src"))
from model_client import ModelClient  # noqa: E402  (HW1 adapter)

SYSTEM_PRIMER = (
    "You are RecallBot, an assistant for grocery supply and food recall notices. "
    "You remember the user across turns through the memory sections you are given: "
    "a long-term summary, the recent conversation, and facts remembered about the user. "
    "Use them when they are relevant. If the memory does not contain something the "
    "user asks about, say you do not know instead of guessing. "
    "Answer in at most 120 words."
)

# ---------------------------------------------------------------- collections


def messages_col():
    return db.get_db()[config.MESSAGES_COLLECTION]


def summaries_col():
    return db.get_db()[config.SUMMARIES_COLLECTION]


def episodes_col():
    return db.get_db()[config.EPISODES_COLLECTION]


def ensure_indexes() -> None:
    """Every memory query filters by user (and session) and sorts by time."""
    messages_col().create_index([("user_id", ASCENDING), ("session_id", ASCENDING),
                                 ("created_at", DESCENDING)], name="ix_user_session_time")
    summaries_col().create_index([("user_id", ASCENDING), ("scope", ASCENDING),
                                  ("created_at", DESCENDING)], name="ix_user_scope_time")
    episodes_col().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)],
                                name="ix_user_time")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- model + embedder

_model: Optional[ModelClient] = None
_embedder = None


def get_model() -> ModelClient:
    global _model
    if _model is None:
        # temperature 0 + fixed seed: the same prompt gives the same reply (Part 3 reruns)
        _model = ModelClient(model=config.CHAT_MODEL, temperature=0.0,
                             options={"num_ctx": config.NUM_CTX, "seed": config.SEED})
    return _model


def get_embedder():
    """MiniLM on the CPU (HW4 lesson: on MPS it fights Ollama for M1 GPU memory)."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    return _embedder


def embed(texts: List[str]) -> np.ndarray:
    """Rows are L2-normalised, so a dot product between two rows is their cosine."""
    vectors = get_embedder().encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return np.asarray(vectors, dtype=np.float32)


# ---------------------------------------------------------------- short-term memory


def save_message(user_id: str, session_id: str, role: str, content: str) -> Dict[str, Any]:
    doc = {"user_id": user_id, "session_id": session_id, "role": role,
           "content": content, "created_at": now_utc()}
    doc["_id"] = messages_col().insert_one(doc).inserted_id
    return doc


def load_short_term(user_id: str, session_id: str, n: int,
                    exclude_id=None) -> List[Dict[str, Any]]:
    """Sliding window: the last n messages of this session, oldest first.

    The message being answered is excluded; it goes into the prompt separately
    as "current message", so it is not counted twice.
    """
    if n <= 0:
        return []
    query: Dict[str, Any] = {"user_id": user_id, "session_id": session_id}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    docs = list(messages_col().find(query, {"role": 1, "content": 1, "created_at": 1})
                .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(n))
    docs.reverse()
    return [{"role": d["role"], "content": d["content"]} for d in docs]


def load_short_term_any(user_id: str, n: int) -> List[Dict[str, Any]]:
    """The user's last n messages across all sessions, oldest first (Part 4 /dream)."""
    docs = list(messages_col().find({"user_id": user_id}, {"role": 1, "content": 1})
                .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(n))
    docs.reverse()
    return [{"role": d["role"], "content": d["content"]} for d in docs]


def count_user_messages(user_id: str, session_id: str) -> int:
    return messages_col().count_documents({"user_id": user_id, "session_id": session_id,
                                           "role": "user"})


# ---------------------------------------------------------------- long-term summaries


def latest_summary(user_id: str, scope: str, session_id: Optional[str] = None) -> Optional[str]:
    query: Dict[str, Any] = {"user_id": user_id, "scope": scope}
    if scope == "session":
        query["session_id"] = session_id
    doc = summaries_col().find_one(query, sort=[("created_at", DESCENDING), ("_id", DESCENDING)])
    return doc["text"] if doc else None


def _bullets(text: str) -> str:
    """Keep only '- ' bullet lines; the model sometimes adds a heading."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bullets = [ln if ln.startswith("- ") else f"- {ln.lstrip('-*• ').strip()}" for ln in lines
               if not ln.endswith(":")]
    return "\n".join(bullets[:8])


def summarize_session(user_id: str, session_id: str) -> Dict[str, Any]:
    """Rolling session summary: previous summary + the messages since it."""
    previous = latest_summary(user_id, "session", session_id)
    # Only the USER's messages: in run 1 the assistant's answers (Listeria, botulism)
    # took over the summary, and the summary repeated a wrongly extracted allergy.
    recent = [m for m in load_short_term(user_id, session_id, 2 * config.SUMMARIZE_EVERY_USER_MSGS)
              if m["role"] == "user"]
    transcript = "\n".join(f"- {m['content']}" for m in recent)
    prompt = (
        "Update the profile of this user from what the USER said. Write 3 to 6 concise "
        "bullet points, each starting with '- '. Keep only facts the user stated about "
        "themselves or their family (name, location, family members and who has which "
        "allergy, stores, purchases, plans, answer-style preferences). Do not include "
        "general knowledge or answers to their questions. If a newer message changes a "
        "fact, keep the newer one. Output only the bullets.\n\n"
        f"Previous summary:\n{previous or '(none)'}\n\nUser's recent messages:\n{transcript}"
    )
    resp = get_model().complete([{"role": "user", "content": prompt}],
                                max_tokens=config.SUMMARY_MAX_TOKENS)
    doc = {"user_id": user_id, "session_id": session_id, "scope": "session",
           "text": _bullets(resp.text), "created_at": now_utc()}
    summaries_col().insert_one(doc)
    return {"scope": "session", "text": doc["text"], "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens, "latency_ms": round(resp.latency_ms, 1)}


def condense_lifetime(user_id: str) -> Dict[str, Any]:
    """Lifetime summary (scope='user', session_id=None) from the latest summary of
    each of the user's recent sessions plus the previous lifetime summary."""
    pipeline = [
        {"$match": {"user_id": user_id, "scope": "session"}},
        {"$sort": {"created_at": -1}},
        {"$group": {"_id": "$session_id", "text": {"$first": "$text"},
                    "at": {"$first": "$created_at"}}},
        {"$sort": {"at": -1}},
        {"$limit": 5},
    ]
    per_session = list(summaries_col().aggregate(pipeline))
    previous = latest_summary(user_id, "user")
    joined = "\n\n".join(f"Session {d['_id']}:\n{d['text']}" for d in per_session)
    prompt = (
        "Condense these session summaries into one lifetime profile of the user. "
        "Write 3 to 6 bullet points starting with '- '. Keep only facts about the user and "
        "their family, not general knowledge. Merge duplicates. If two facts conflict, keep "
        "the most recent one. Output only the bullets.\n\n"
        f"Previous lifetime summary:\n{previous or '(none)'}\n\n{joined}"
    )
    resp = get_model().complete([{"role": "user", "content": prompt}],
                                max_tokens=config.SUMMARY_MAX_TOKENS)
    doc = {"user_id": user_id, "session_id": None, "scope": "user",
           "text": _bullets(resp.text), "created_at": now_utc()}
    summaries_col().insert_one(doc)
    return {"scope": "user", "text": doc["text"], "sessions_used": len(per_session),
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
            "latency_ms": round(resp.latency_ms, 1)}


def maybe_summarize(user_id: str, session_id: str) -> List[Dict[str, Any]]:
    """Trigger: every M-th user message in the session -> session summary;
    every LIFETIME_EVERY-th session summary of the user -> lifetime summary."""
    events: List[Dict[str, Any]] = []
    if count_user_messages(user_id, session_id) % config.SUMMARIZE_EVERY_USER_MSGS != 0:
        return events
    events.append(summarize_session(user_id, session_id))
    n_session = summaries_col().count_documents({"user_id": user_id, "scope": "session"})
    if n_session % config.LIFETIME_EVERY_SESSION_SUMMARIES == 0:
        events.append(condense_lifetime(user_id))
    return events


# ---------------------------------------------------------------- episodic memory

FACT_SCHEMA = {
    "type": "object",
    "properties": {"facts": {"type": "array", "maxItems": config.MAX_FACTS_PER_MESSAGE,
                             "items": {"type": "object",
                                       "properties": {"fact": {"type": "string"},
                                                      "importance": {"type": "number"}},
                                       "required": ["fact", "importance"]}}},
    "required": ["facts"],
}


_STOP = {"user", "users", "user's", "xu", "the", "a", "an", "is", "are", "was", "has", "have",
         "had", "to", "of", "in", "at", "on", "for", "and", "or", "with", "from", "his", "her",
         "their", "my", "i", "me", "be", "will", "does", "do", "who", "that", "this", "it"}


def _words(text: str) -> List[str]:
    return [w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split()
            if w not in _STOP and len(w) > 1]


def statement_part(message: str) -> str:
    """Drop question sentences: a question asks for information, it does not state any.
    (Run 1: "Where do I usually shop now?" produced the invented fact "User usually shops at Walmart".)"""
    import re
    sentences = re.split(r"(?<=[.!?])\s+", message.strip())
    return " ".join(s for s in sentences if s and not s.rstrip().endswith("?"))


def grounded(fact: str, source: str) -> bool:
    """Keep a fact only if most of its content words occur in what the user said.
    Prefix match (4 letters) lets 'allergy' match 'allergic' and 'shops' match 'shop'.
    (Run 1: "Summarize what you know about me" produced "User lives in New York City".)"""
    fact_words = _words(fact)
    if not fact_words:
        return False
    stems = {w[:4] for w in _words(source)}
    hits = sum(1 for w in fact_words if w[:4] in stems)
    return hits / len(fact_words) >= 0.5


def extract_facts(message: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Up to 3 short facts the user STATED, each with importance 0..1.

    Three guards against memory poisoning, all added after run 1 (see AI_USE.md):
      1 questions are removed before extraction (statement_part)
      2 the prompt requires facts to be about the right person, with examples
      3 a fact whose words are not in the message is dropped (grounded)
    Uses Ollama structured output (format = JSON schema); an unparsable reply gives no facts.
    """
    statements = statement_part(message)
    if not statements:
        return [], {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0,
                    "skipped": "question only"}
    prompt = (
        "Extract facts that the user EXPLICITLY STATES in the message below, to remember "
        "in later conversations: identity, location, family members, allergies, diet, "
        "stores, purchases, plans, and preferences about how to answer.\n"
        "Rules:\n"
        "- At most 3 facts. Only what the message says; never guess or add details.\n"
        "- Attribute each fact to the right person. A fact about a family member is about "
        "that person, not the user.\n"
        "- Write each fact as a short sentence starting with 'User' or \"User's <relative>\".\n"
        "- importance 0..1: 1 = safety-critical (allergy, medical diet), 0.7 = stable "
        "personal fact, 0.3 = minor preference.\n"
        "- If the message states no fact about the user, return {\"facts\": []}.\n"
        "Examples:\n"
        "Message: My son is allergic to milk.\n"
        "{\"facts\": [{\"fact\": \"User's son is allergic to milk.\", \"importance\": 1.0}]}\n"
        "Message: Thanks, that helps.\n"
        "{\"facts\": []}\n\n"
        f"Message: {statements}"
    )
    resp = get_model().complete([{"role": "user", "content": prompt}],
                                response_format=FACT_SCHEMA,
                                max_tokens=config.EXTRACT_MAX_TOKENS)
    usage = {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
             "latency_ms": round(resp.latency_ms, 1)}
    try:
        raw = json.loads(resp.text).get("facts", [])
    except (json.JSONDecodeError, AttributeError):
        return [], {**usage, "parse_error": True}
    facts, rejected = [], []
    for item in raw[: config.MAX_FACTS_PER_MESSAGE]:
        text = str(item.get("fact", "")).strip()[:200]
        if not text:
            continue
        if not grounded(text, statements):
            rejected.append(text)
            continue
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        facts.append({"fact": text, "importance": round(min(max(importance, 0.0), 1.0), 2)})
    if rejected:
        usage["rejected_ungrounded"] = rejected
    return facts, usage


def store_episodes(user_id: str, session_id: str,
                   facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Embed and insert facts; skip one that nearly repeats a stored fact
    (cosine >= EPISODE_DEDUP_COSINE, the HW4 near-duplicate idea)."""
    if not facts:
        return []
    vectors = embed([f["fact"] for f in facts])
    existing = list(episodes_col().find({"user_id": user_id}, {"embedding": 1}))
    matrix = (np.asarray([e["embedding"] for e in existing], dtype=np.float32)
              if existing else np.zeros((0, vectors.shape[1]), dtype=np.float32))
    stored = []
    for fact, vec in zip(facts, vectors):
        if matrix.shape[0] and float((matrix @ vec).max()) >= config.EPISODE_DEDUP_COSINE:
            continue
        doc = {"user_id": user_id, "session_id": session_id, "fact": fact["fact"],
               "importance": fact["importance"], "embedding": vec.tolist(),
               "created_at": now_utc()}
        episodes_col().insert_one(doc)
        matrix = np.vstack([matrix, vec[None, :]])
        stored.append({"fact": fact["fact"], "importance": fact["importance"]})
    return stored


def retrieve_episodes(user_id: str, query_text: str, k: int) -> List[Dict[str, Any]]:
    """Top-k of the user's facts by cosine similarity to query_text.

    All of the user's episodes are scored in Python (brute force, like FAISS
    IndexFlatIP in HW4). Fine for one user's few hundred facts; at scale this
    would move into a vector index in the database.
    """
    docs = list(episodes_col().find({"user_id": user_id},
                                    {"fact": 1, "importance": 1, "embedding": 1}))
    if not docs or k <= 0:
        return []
    matrix = np.asarray([d["embedding"] for d in docs], dtype=np.float32)
    scores = matrix @ embed([query_text])[0]
    order = np.argsort(-scores)[:k]
    return [{"fact": docs[i]["fact"], "importance": docs[i]["importance"],
             "score": round(float(scores[i]), 4)}
            for i in order if scores[i] >= config.EPISODE_MIN_SCORE]


# ---------------------------------------------------------------- prompt assembly


def build_prompt(session_summary: Optional[str], lifetime_summary: Optional[str],
                 window: List[Dict[str, str]], current: str,
                 facts: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    """Order required by the assignment:
    system primer + long-term summaries + short-term window + current message + episodic facts.

    Returns the chat messages and the text of each section separately, so Part 3
    can count the tokens each memory type costs.
    """
    long_term = ""
    if lifetime_summary or session_summary:
        long_term = ("Long-term memory about this user:\n"
                     f"Lifetime summary:\n{lifetime_summary or '(none yet)'}\n"
                     f"This session so far:\n{session_summary or '(none yet)'}")
    facts_text = ""
    if facts:
        facts_text = ("Facts remembered about this user (most relevant first):\n"
                      + "\n".join(f"- {f['fact']}" for f in facts))

    messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PRIMER}]
    if long_term:
        messages.append({"role": "system", "content": long_term})
    messages.extend({"role": m["role"], "content": m["content"]} for m in window)
    messages.append({"role": "user", "content": current})
    if facts_text:
        messages.append({"role": "system", "content": facts_text})

    sections = {
        "system_primer": SYSTEM_PRIMER,
        "long_term_summary": long_term,
        "short_term_window": "\n".join(f"{m['role']}: {m['content']}" for m in window),
        "current_message": current,
        "episodic_facts": facts_text,
    }
    return messages, sections


# ---------------------------------------------------------------- Part 3: policy + logging

WINDOW_POLICIES = ("full", "compress_assistant")


def first_sentence(text: str, limit: int) -> str:
    """'Yes. Class I means...' -> 'Yes.'  Cut at the first . ! ? or at `limit` chars."""
    text = " ".join(text.split())
    for i, ch in enumerate(text):
        if ch in ".!?" and i >= 15:
            return text[: i + 1][:limit]
        if i >= limit:
            break
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def apply_window_policy(window: List[Dict[str, str]], policy: str) -> List[Dict[str, str]]:
    """Part 3-4 compression policy.

    full                the window as stored
    compress_assistant  user messages verbatim; each assistant reply cut to its first
                        sentence (<= ASSISTANT_KEEP_CHARS). Facts about the user live in
                        the user's own messages; the replies are most of the tokens.
    """
    if policy == "full":
        return window
    if policy == "compress_assistant":
        return [m if m["role"] == "user"
                else {"role": m["role"], "content": first_sentence(m["content"],
                                                                   config.ASSISTANT_KEEP_CHARS)}
                for m in window]
    raise ValueError(f"unknown window policy {policy!r}")


def log_turn(path, result: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Append one JSON line per /api/chat call: tokens per section, latency, memory work."""
    sections = result["_sections"]
    tokens = {name: token_count.count(text) for name, text in sections.items()}
    usage = result["usage"]
    summaries = result["memory_written"]["summaries"]
    row = {
        "ts": now_utc().isoformat(),
        **(extra or {}),
        "user_id": result["user_id"], "session_id": result["session_id"],
        "model": usage["model"], "tokenizer": token_count.tokenizer_name(),
        "short_term_n": result["memory_used"]["short_term"]["n"],
        "window_policy": result["window_policy"],
        "window_messages": result["memory_used"]["short_term"]["count"],
        "facts_retrieved": len(result["memory_used"]["episodic_facts"]),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "tokens_system_primer": tokens["system_primer"],
        "tokens_long_term_summary": tokens["long_term_summary"],
        "tokens_short_term_window": tokens["short_term_window"],
        "tokens_current_message": tokens["current_message"],
        "tokens_episodic_facts": tokens["episodic_facts"],
        "template_overhead": usage["prompt_tokens"] - sum(tokens.values()),
        "chat_latency_ms": usage["chat_latency_ms"],
        "total_latency_ms": usage["total_latency_ms"],
        # memory upkeep: extra model calls this turn caused
        "extract_input_tokens": usage["extract"].get("input_tokens", 0),
        "extract_output_tokens": usage["extract"].get("output_tokens", 0),
        "summary_input_tokens": sum(e["input_tokens"] for e in summaries),
        "summary_output_tokens": sum(e["output_tokens"] for e in summaries),
        "summaries_written": [e["scope"] for e in summaries],
        "episodes_added": len(result["memory_written"]["episodes_added"]),
        "reply": result["reply"],
    }
    if path:
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# ---------------------------------------------------------------- one chat turn


def chat_turn(user_id: str, message: str, session_id: Optional[str] = None,
              short_term_n: Optional[int] = None,
              window_policy: str = "full") -> Dict[str, Any]:
    started = time.perf_counter()
    session_id = session_id or new_session_id()
    n = config.SHORT_TERM_N if short_term_n is None else short_term_n

    user_doc = save_message(user_id, session_id, "user", message)                 # 1
    window = load_short_term(user_id, session_id, n, exclude_id=user_doc["_id"])  # 2
    window = apply_window_policy(window, window_policy)
    session_summary = latest_summary(user_id, "session", session_id)             # 3
    lifetime_summary = latest_summary(user_id, "user")
    facts = retrieve_episodes(user_id, message, config.TOP_K)                     # 4
    messages, sections = build_prompt(session_summary, lifetime_summary,          # 5
                                      window, message, facts)
    resp = get_model().complete(messages, max_tokens=config.REPLY_MAX_TOKENS)    # 6
    reply = resp.text.strip()
    save_message(user_id, session_id, "assistant", reply)                         # 7
    new_facts, extract_usage = extract_facts(message)                             # 8
    stored = store_episodes(user_id, session_id, new_facts)
    summary_events = maybe_summarize(user_id, session_id)                         # 9

    return {
        "user_id": user_id,
        "session_id": session_id,
        "window_policy": window_policy,
        "reply": reply,
        "memory_used": {
            "short_term": {"n": n, "count": len(window), "messages": window},
            "long_term_summary": {"session": session_summary, "lifetime": lifetime_summary},
            "episodic_facts": facts,
        },
        "memory_written": {"episodes_added": stored, "summaries": summary_events},
        "usage": {
            "model": resp.model,
            "prompt_tokens": resp.input_tokens,
            "completion_tokens": resp.output_tokens,
            "chat_latency_ms": round(resp.latency_ms, 1),
            "extract": extract_usage,
            "total_latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "section_chars": {k: len(v) for k, v in sections.items()},
        },
        "_sections": sections,      # removed by the router; kept for Part 3 logging
    }


# ---------------------------------------------------------------- read-only views


def memory_view(user_id: str, n_messages: int = 16, n_facts: int = 20) -> Dict[str, Any]:
    """GET /api/memory/{user_id}: newest messages, summaries and facts (no embeddings)."""
    msgs = list(messages_col().find({"user_id": user_id},
                                    {"_id": 0, "session_id": 1, "role": 1, "content": 1,
                                     "created_at": 1})
                .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(n_messages))
    msgs.reverse()
    sess = summaries_col().find_one({"user_id": user_id, "scope": "session"},
                                    {"_id": 0}, sort=[("created_at", DESCENDING)])
    life = summaries_col().find_one({"user_id": user_id, "scope": "user"},
                                    {"_id": 0}, sort=[("created_at", DESCENDING)])
    facts = list(episodes_col().find({"user_id": user_id},
                                     {"_id": 0, "embedding": 0})
                 .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).limit(n_facts))
    return {"user_id": user_id, "messages": msgs, "session_summary": sess,
            "lifetime_summary": life, "episodic_facts": facts}


def aggregate_view(user_id: str, n_summaries: int = 5) -> Dict[str, Any]:
    """GET /api/aggregate/{user_id}: messages per day ($group, like SQL GROUP BY)."""
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                    "messages": {"$sum": 1},
                    "user_messages": {"$sum": {"$cond": [{"$eq": ["$role", "user"]}, 1, 0]}}}},
        {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "date": "$_id", "messages": 1, "user_messages": 1}},
    ]
    daily = list(messages_col().aggregate(pipeline))
    recent = list(summaries_col().find({"user_id": user_id},
                                       {"_id": 0, "scope": 1, "session_id": 1, "text": 1,
                                        "created_at": 1})
                  .sort([("created_at", DESCENDING)]).limit(n_summaries))
    return {"user_id": user_id, "daily_message_counts": daily, "recent_summaries": recent}
