"""HW6 Part 1-I: create s9275_doc.recall_notices with database-side validation.

    python code/doc_app/init_db.py           create/refresh validator + indexes
    python code/doc_app/init_db.py --seed    ... and insert 5 sample notices if empty

Safe to run again: an existing collection gets its validator replaced (collMod)
instead of failing. Compare HW5's hw05_migrate.sql, which could only run once.
"""
import sys
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import WriteError

import config

# --- the schema the DATABASE enforces ($jsonSchema) ---------------------------
# MongoDB accepts any document unless a collection has a validator.
# bsonType "date" means a real BSON date, not a string like "2026-10-18".
NOTICE_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["product_name", "recall_number", "status", "category",
                     "recall_date", "created_at", "updated_at"],
        "additionalProperties": False,          # unknown fields are rejected
        "properties": {
            "_id": {"bsonType": "objectId"},
            "product_name": {"bsonType": "string", "minLength": 1,
                             "maxLength": config.PRODUCT_NAME_MAX},
            "reason": {"bsonType": ["string", "null"], "maxLength": config.REASON_MAX},
            "recall_number": {"bsonType": "string",
                              "pattern": config.RECALL_NUMBER_PATTERN},
            "status": {"enum": list(config.STATUSES)},
            "category": {"enum": list(config.CATEGORIES)},
            "recall_date": {"bsonType": "date"},
            # embedded sub-document: HW5 needed a firms table + JOIN for this
            "firm": {
                "bsonType": ["object", "null"],
                "required": ["name"],
                "additionalProperties": False,
                "properties": {
                    "name": {"bsonType": "string", "minLength": 1, "maxLength": 100},
                    "state": {"bsonType": ["string", "null"], "pattern": "^[A-Z]{2}$"},
                },
            },
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}


def utc(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


# Fictional sample notices (product and firm names are made up).
SAMPLES = [
    ("Honey Oat Granola Bars", "F-0101-2026", "Undeclared Allergen", "ongoing",
     "Contains undeclared peanuts.", utc(2026, 9, 2), "Sunrise Pantry Foods", "CA"),
    ("Frozen Spinach 12 oz", "F-0102-2026", "Bacterial Contamination", "ongoing",
     "Potential Listeria monocytogenes contamination.", utc(2026, 9, 9), "Green Valley Farms", "WA"),
    ("Spiced Tomato Salsa", "F-0103-2026", "Foreign Material", "completed",
     "Glass fragments found in some jars.", utc(2026, 8, 21), "Casa Verde Kitchens", "TX"),
    ("Almond Milk Vanilla", "F-0104-2026", "Mislabeling", "terminated",
     None, utc(2026, 7, 15), "Bay Dairy Alternatives", "CA"),
    ("Smoked Salmon Slices", "F-0105-2026", "Bacterial Contamination", "ongoing",
     "Possible Clostridium botulinum growth.", utc(2026, 10, 1), "North Coast Seafood", "OR"),
]


def main() -> None:
    print(f"Xu Wang | DATA 260 HW6 Part 1 | init_db  ({datetime.now():%Y-%m-%d %H:%M:%S})")
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
    db = client[config.DB_NAME]
    name = config.NOTICES_COLLECTION

    # 1) collection + validator (create first time, collMod afterwards)
    if name in db.list_collection_names():
        db.command("collMod", name, validator=NOTICE_VALIDATOR,
                   validationLevel="strict", validationAction="error")
        print(f"[ok] {config.DB_NAME}.{name} exists -> validator replaced (collMod)")
    else:
        db.create_collection(name, validator=NOTICE_VALIDATOR,
                             validationLevel="strict", validationAction="error")
        print(f"[ok] created {config.DB_NAME}.{name} with $jsonSchema validator")
    col = db[name]

    # 2) indexes: unique recall_number (-> 409 in the API), newest-first listing
    col.create_index([("recall_number", ASCENDING)], unique=True, name="uniq_recall_number")
    col.create_index([("recall_date", DESCENDING)], name="ix_recall_date")
    print("[ok] indexes:", sorted(col.index_information()))

    # 3) prove the DATABASE itself rejects a bad document (no API involved)
    bad = {"product_name": "x" * 150, "recall_number": "ABC-12", "status": "lost",
           "category": "Color", "recall_date": "2026-10-18"}
    try:
        col.insert_one(bad)
        col.delete_one({"_id": bad["_id"]})
        print("[FAIL] invalid document was accepted - validator not active")
    except WriteError as exc:
        print(f"[ok] invalid document rejected by MongoDB: code {exc.code} "
              f"({exc.details.get('errmsg')})")

    # 4) optional sample data
    if "--seed" in sys.argv:
        if col.count_documents({}) == 0:
            now = datetime.now(timezone.utc)
            docs = [{"product_name": p, "recall_number": rn, "category": cat, "status": st,
                     "reason": reason, "recall_date": d,
                     "firm": {"name": firm, "state": state},
                     "created_at": now, "updated_at": now}
                    for p, rn, cat, st, reason, d, firm, state in SAMPLES]
            col.insert_many(docs)
            print(f"[ok] inserted {len(docs)} sample notices")
        else:
            print("[skip] collection not empty, no samples inserted")

    print(f"[ok] {name} now holds {col.count_documents({})} documents")


if __name__ == "__main__":
    main()
