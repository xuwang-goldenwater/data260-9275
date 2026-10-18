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
