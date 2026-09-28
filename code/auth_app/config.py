"""Section 0 values and settings shared by every HW4 module."""
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
DOMAIN_ID = SID4 % 8                 # 3

DB_NAME = f"{PREFIX}_rel"            # s9275_rel

MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

# Session rules carried over from HW3: 15 minutes idle, 1 hour absolute.
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "900"))
ABSOLUTE_TIMEOUT_SECONDS = 3600
COOKIE_NAME = f"{PREFIX}_session"

# The React dev server (Vite) runs on 5173 and calls this API on 8275.
FRONTEND_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Login used by the React app, Postman and the scripts. Created by seed_hw04.py.
DEMO_NAME = "Xu Wang"
DEMO_EMAIL = os.getenv("HW4_DEMO_EMAIL", "demo@s9275.example.com")
DEMO_PASSWORD = os.getenv("HW4_DEMO_PASSWORD", "recall-demo-9275")

CATEGORIES = (
    "Undeclared Allergen",
    "Bacterial Contamination",
    "Foreign Material",
    "Mislabeling",
)

MAX_PAGE_SIZE = 200
