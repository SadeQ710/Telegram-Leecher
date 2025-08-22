"""
MongoDB backed persistence helpers.

This module defines a minimal asynchronous API for storing and
retrieving per‑user verification state.  It relies on the ``pymongo``
package which is declared as a dependency in ``requirements.txt`` and
therefore should already be available in the runtime environment.  If
you wish to switch to a different storage backend you can do so by
providing alternative implementations of these functions.  Each
function returns an awaitable to play nicely with the rest of the
coroutine based codebase.  Internally however all I/O is performed
synchronously on the current thread – if more sophisticated
concurrency is required then the helpers could be adapted to use
``motor`` or another async driver.

The stored schema for a user document is very simple.  Each user has
an integer ``user_id`` primary key and the following keys:

``verify_token``: ``str``
    A random token generated when a verification link is created.  If
    no token is outstanding then this field may be an empty string.

``is_verified``: ``bool``
    Whether the user has successfully verified.  Once set it remains
    true until a token expires and the user must verify again.

``verified_time``: ``float``
    Unix timestamp representing when the current verification token
    was confirmed.  Used for expiration calculations.

``link``: ``str``
    The last verification link issued to the user.  Stored purely for
    convenience so that the same link can be re‑used in successive
    messages instead of generating a new token repeatedly.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, errors

from ..config import DB_URI, DB_NAME

_client: Optional[MongoClient] = None


def _get_collection():
    """Return the MongoDB collection for users, creating the client lazily.

    This helper centralises connection management.  It caches the
    client object so repeated calls do not create additional
    connections.  If the database or collection do not exist they will
    be created automatically by MongoDB on first insert.
    """
    global _client
    if _client is None:
        _client = MongoClient(DB_URI)
    db = _client[DB_NAME]
    return db["users"]


async def present_user(user_id: int) -> bool:
    """Return True if a user record exists, False otherwise."""
    col = _get_collection()
    return col.count_documents({"user_id": user_id}, limit=1) > 0


async def add_user(user_id: int) -> None:
    """Create a new user record with default verification state.

    If a record for the given ``user_id`` already exists then this
    function simply returns without modifying anything.
    """
    col = _get_collection()
    try:
        col.insert_one(
            {
                "user_id": user_id,
                "verify_token": "",
                "is_verified": False,
                "verified_time": 0.0,
                "link": "",
            }
        )
    except errors.DuplicateKeyError:
        # Record exists – nothing to do
        return


async def full_userbase() -> List[Dict[str, Any]]:
    """Return a list of all user documents for administrative purposes."""
    col = _get_collection()
    return list(col.find())


async def del_user(user_id: int) -> None:
    """Remove a user record completely."""
    col = _get_collection()
    col.delete_one({"user_id": user_id})


async def db_verify_status(user_id: int) -> Dict[str, Any]:
    """Return the verification status document for a given user.

    If the user does not exist yet this function will create a default
    record before returning it.
    """
    col = _get_collection()
    doc = col.find_one({"user_id": user_id})
    if doc is None:
        # Create default record on demand
        await add_user(user_id)
        doc = col.find_one({"user_id": user_id})
    return doc


async def db_update_verify_status(user_id: int, data: Dict[str, Any]) -> None:
    """Update a user's verification document with the provided fields."""
    col = _get_collection()
    col.update_one({"user_id": user_id}, {"$set": data}, upsert=True)


__all__ = [
    "present_user",
    "add_user",
    "full_userbase",
    "del_user",
    "db_verify_status",
    "db_update_verify_status",
]