"""
HW4 Part 3 step 1 - seed 200 firms and 5,000 recall notices with SEED = 9275.

    python code/seed_hw04.py      # or: make seed    (run make db-init first)

- Every value comes from random.Random(SEED), so two runs produce identical
  rows. A SHA-256 of all generated rows is written to
  reports/hw04/raw/seed_manifest.json so a grader can confirm that.
- Each notice gets a firm_id in 1..200, so all 5,000 notices have related data
  and the list endpoints always have a firm to fetch (Part 3 step 2).
- Also creates the demo login user (config.DEMO_EMAIL) with a bcrypt hash.
- Re-running empties firms and recall_notices first; users and sessions stay.
"""
import hashlib
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import bcrypt
import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code" / "auth_app"))
import config  # noqa: E402

N_FIRMS = 200
N_NOTICES = 5000
RAW_DIR = ROOT / "reports" / "hw04" / "raw"

# ---- word lists --------------------------------------------------------------

FIRM_WORDS = ["Sunrise", "Harbor", "Golden", "Prairie", "Blue Ridge", "Cedar", "Summit",
              "Maple", "River Bend", "Silver Creek", "Evergreen", "Oak Hill", "Pacific",
              "Lakeside", "Red Barn", "Stone Mill", "Willow", "Coastal", "Heartland",
              "Pine Valley", "Northstar", "Meadow", "Bayview", "Orchard"]
FIRM_TYPES = ["Foods, Inc.", "Farms LLC", "Provisions Co.", "Bakery Inc.", "Dairy Co.",
              "Seafood LLC", "Kitchens Inc.", "Snacks Co.", "Produce LLC", "Mills Inc."]
STATES = ["CA", "OR", "WA", "NV", "AZ", "TX", "IL", "WI", "MN", "IA", "OH", "MI",
          "NY", "NJ", "PA", "GA", "FL", "NC", "CO", "UT"]

BRANDS = ["Sunrise Valley", "Harbor Point", "Golden Fields", "Prairie Gold", "Mountain Fresh",
          "Little Acorn", "Blue Heron", "Green Leaf", "Farmhouse", "Market Basket",
          "Coastal Catch", "Hearth & Home", "Good Grain", "Morning Dew", "True North"]
PRODUCTS = ["Creamy Peanut Butter", "Frozen Diced Onions", "Chocolate Chip Cookies",
            "Shredded Mozzarella", "Baby Spinach", "Chicken Salad", "Almond Granola",
            "Frozen Raw Shrimp", "Whole Milk Yogurt", "Sourdough Bread", "Hummus",
            "Ground Turkey", "Pistachio Ice Cream", "Enoki Mushrooms", "Protein Bars",
            "Infant Formula", "Tahini", "Smoked Salmon", "Cheddar Crackers", "Fruit Cups"]
SIZES = ["8 oz", "12 oz", "16 oz", "1 lb bag", "2 lb bag", "6-pack", "32 oz tub", "family size"]

# Weights follow DOMAIN_SCHEMA.md (Q1 2026 FDA shares); the rest is mislabeling.
CATEGORY_WEIGHTS = [("Undeclared Allergen", 41), ("Bacterial Contamination", 16),
                    ("Foreign Material", 17), ("Mislabeling", 26)]

DATE_START = date(2021, 1, 1)
DATE_DAYS = (date(2026, 8, 31) - DATE_START).days


def generate(rng: random.Random):
    firm_names = [f"{w} {t}" for w in FIRM_WORDS for t in FIRM_TYPES]   # 240 unique
    rng.shuffle(firm_names)
    firms = [(firm_names[i], rng.choice(STATES)) for i in range(N_FIRMS)]

    categories = [c for c, _ in CATEGORY_WEIGHTS]
    weights = [w for _, w in CATEGORY_WEIGHTS]
    notices = []
    for _ in range(N_NOTICES):
        name = f"{rng.choice(BRANDS)} {rng.choice(PRODUCTS)}, {rng.choice(SIZES)}"
        category = rng.choices(categories, weights)[0]
        firm_id = rng.randint(1, N_FIRMS)
        recall_date = DATE_START + timedelta(days=rng.randint(0, DATE_DAYS))
        notices.append((name, category, firm_id, recall_date.isoformat()))
    return firms, notices


def main():
    rng = random.Random(config.SEED)
    firms, notices = generate(rng)
    digest = hashlib.sha256(json.dumps([firms, notices]).encode("utf-8")).hexdigest()

    conn = pymysql.connect(host=config.MYSQL_HOST, port=config.MYSQL_PORT,
                           user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
                           database=config.DB_NAME, charset="utf8mb4")
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("TRUNCATE TABLE recall_notices")     # also resets AUTO_INCREMENT
        cur.execute("TRUNCATE TABLE firms")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")

        cur.executemany("INSERT INTO firms (name, state) VALUES (%s, %s)", firms)
        cur.executemany(
            "INSERT INTO recall_notices (product_name, category, firm_id, recall_date) "
            "VALUES (%s, %s, %s, %s)", notices)

        password_hash = bcrypt.hashpw(config.DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode()
        cur.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE name = VALUES(name), password_hash = VALUES(password_hash)",
            (config.DEMO_NAME, config.DEMO_EMAIL, password_hash))
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM firms")
        n_firms = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM recall_notices")
        n_notices = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT firm_id) FROM recall_notices")
        n_used = cur.fetchone()[0]
        cur.execute("SELECT category, COUNT(*) FROM recall_notices GROUP BY category ORDER BY 2 DESC")
        by_category = {c: n for c, n in cur.fetchall()}
    conn.close()

    manifest = {
        "seed": config.SEED, "database": config.DB_NAME,
        "firms": n_firms, "recall_notices": n_notices,
        "firms_referenced_by_notices": n_used,
        "notices_by_category": by_category,
        "sha256_of_generated_rows": digest,
        "first_notices": notices[:3], "first_firms": firms[:3],
        "demo_user": config.DEMO_EMAIL,
    }
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "seed_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
