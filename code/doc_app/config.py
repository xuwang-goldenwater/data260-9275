"""Section 0 values and settings shared by every HW6 doc_app module.

HW6 Part 1 is the HW5 recall-notice CRUD with MongoDB in place of MySQL.
Same Section 0 values as code/auth_app/config.py; only the storage settings differ.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent   # repo root
load_dotenv(ROOT / ".env")

SID4 = 9275
PORT_BASE = 8000 + SID4 % 900        # 8275
PREFIX = f"s{SID4}"                  # s9275
SEED = SID4                          # 9275
VERIFY_SEED = 260000 + SID4          # 269275
DOMAIN_ID = SID4 % 8                 # 3 = Grocery supply and recall notices

# MongoDB runs in Docker:  docker run -d --name s9275-mongo -p 27017:27017 ...
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = f"{PREFIX}_doc"            # s9275_doc  (HW4/HW5 MySQL was s9275_rel)
NOTICES_COLLECTION = "recall_notices"

# Allowed values. The same lists feed the Pydantic schemas (API layer)
# and the $jsonSchema validator (database layer), so the two cannot drift apart.
CATEGORIES = (                       # same four categories as HW4/HW5
    "Undeclared Allergen",
    "Bacterial Contamination",
    "Foreign Material",
    "Mislabeling",
)
STATUSES = ("ongoing", "completed", "terminated")   # FDA recall status
DEFAULT_STATUS = "ongoing"

PRODUCT_NAME_MAX = 100               # "required short text field (max 100 characters)"
REASON_MAX = 1000                    # optional description
RECALL_NUMBER_PATTERN = r"^F-\d{4}-\d{4}$"           # e.g. F-0123-2026, unique (HW5)

# The browser test page / Postman may call from anywhere on localhost.
FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173",
                    "http://localhost:8275", "http://127.0.0.1:8275"]

# ---- HW6 Part 2: memory (same database, new collections) ---------------------
MESSAGES_COLLECTION = "messages"
SUMMARIES_COLLECTION = "summaries"
EPISODES_COLLECTION = "episodes"

# Model through the HW1 adapter (src/model_client.py). qwen2.5:3b fits 100% in
# the M1 8 GB GPU; qwen3:8b ran 24% on the CPU in HW5. num_ctx 8192: Ollama's
# default 4096 would silently cut long prompts (Part 3 runs SHORT_TERM_N = 30).
CHAT_MODEL = os.getenv("HW6_MODEL", "qwen2.5:3b")
NUM_CTX = int(os.getenv("HW6_NUM_CTX", "8192"))
REPLY_MAX_TOKENS = 200
SUMMARY_MAX_TOKENS = 200
EXTRACT_MAX_TOKENS = 150

SHORT_TERM_N = int(os.getenv("SHORT_TERM_N", "12"))   # Part 3 sweeps 4 / 12 / 30
SUMMARIZE_EVERY_USER_MSGS = 4                          # M
LIFETIME_EVERY_SESSION_SUMMARIES = 2                   # condense into scope='user'

# Episodic memory: MiniLM (HW3/HW4), cosine on L2-normalised vectors
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_FACTS_PER_MESSAGE = 3
TOP_K = 3
# Pure top-k, as the assignment states. A 0.2 floor was tried first and dropped
# "allergic to peanuts" for "Which recalls should I worry about?" (no shared words,
# low MiniLM cosine). Missing an allergy costs more than 3 extra facts in the prompt.
EPISODE_MIN_SCORE = float(os.getenv("HW6_EPISODE_MIN_SCORE", "0.0"))
EPISODE_DEDUP_COSINE = 0.95      # a new fact this close to a stored one is skipped

# ---- HW6 Part 3: memory cost --------------------------------------------------
ASSISTANT_KEEP_CHARS = 160       # compress_assistant policy: keep the first sentence, at most this long
CHAT_LOG_PATH = ROOT / "reports" / "hw06" / "raw" / "api_chat_turns.jsonl"   # every /api/chat call
