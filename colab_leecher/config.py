"""
Configuration module for the Colab Leecher bot.

This module centralises a handful of environment variables used by the
downloader components.  It is deliberately kept extremely small and
self‑contained so it can be imported without triggering any of the
heavier parts of the codebase.  If a variable is not present in
``os.environ`` then a reasonable default will be used.  The defaults
below match the values found in the original terabox example
application bundled alongside this repository.  If you wish to
override a value simply set the appropriate environment variable
before launching the bot (for example by using a ``.env`` file).

The following variables are available:

``DB_URI``
    The MongoDB connection URI.  Defaults to a bare Atlas URL.  See
    https://docs.mongodb.com/manual/reference/connection-string/ for
    details.

``DB_NAME``
    The name of the database to use within the MongoDB cluster.  The
    original sample code stores user records in a database named
    ``leech_bot_db`` and the same value is used as the default here.

``SHORTLINK_URL``
    The base URL of the shortener service used to generate token
    verification links.  If unset the fallback value of
    ``ziplinker.net`` will be used.  This value should not include
    trailing slashes.

``SHORTLINK_API``
    The API key used when contacting the shortener service.  In the
    absence of a user provided key the placeholder
    ``your_api_key_here`` will be used which will result in
    verification links not resolving correctly.  You should supply
    your own key.

``VERIFY_EXPIRE``
    Number of seconds a verification token remains valid for before
    expiring.  By default tokens are valid for 12 hours (43200 seconds).

``IS_VERIFY``
    Boolean flag controlling whether the verification system is
    enforced.  Defaults to ``True`` meaning users must verify before
    downloading from terabox.  Set to ``False`` to disable the
    verification workflow entirely.

Because the environment variables are read at import time it is
important that this module is imported after any call to
``dotenv.load_dotenv`` (should you choose to use the ``python‑dotenv``
package).
"""

import os

# Read environment variables with sensible defaults
DB_URI: str = os.environ.get("DATABASE_URL", "mongodb+srv://user:pass@cluster.mongodb.net/")
DB_NAME: str = os.environ.get("DATABASE_NAME", "leech_bot_db")
SHORTLINK_URL: str = os.environ.get("SHORTLINK_URL", "ziplinker.net")
SHORTLINK_API: str = os.environ.get("SHORTLINK_API", "your_api_key_here")

try:
    VERIFY_EXPIRE: int = int(os.environ.get("VERIFY_EXPIRE", 43200))
except ValueError:
    VERIFY_EXPIRE = 43200

IS_VERIFY: bool = os.environ.get("IS_VERIFY", "True").lower() == "true"

__all__ = [
    "DB_URI",
    "DB_NAME",
    "SHORTLINK_URL",
    "SHORTLINK_API",
    "VERIFY_EXPIRE",
    "IS_VERIFY",
]