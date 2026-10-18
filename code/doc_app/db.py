"""PyMongo connection for doc_app (HW6). Plays the role of auth_app/database.py in HW4/HW5.

MongoClient keeps its own connection pool and is thread-safe, so one client is
created lazily and shared by every request. There is no ORM session to open and
close per request (HW5 needed Depends(get_db) for that).
"""
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

import config

_client = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        # tz_aware=True: dates come back as UTC-aware datetimes, so the API
        # returns "...+00:00" instead of a naive time that looks local.
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True)
    return _client


def get_db() -> Database:
    return get_client()[config.DB_NAME]


def get_notices() -> Collection:
    return get_db()[config.NOTICES_COLLECTION]


def ping() -> dict:
    return get_client().admin.command("ping")
