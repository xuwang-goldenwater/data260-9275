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

# HW7: JWT bearer tokens replace the HW4 server-side sessions (kept at tag hw4).
# The secret signs every token; set JWT_SECRET in .env for anything but local dev.
JWT_SECRET = os.getenv("JWT_SECRET", f"dev-only-secret-{PREFIX}-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
ROLES = ("reader", "writer", "moderator")

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
