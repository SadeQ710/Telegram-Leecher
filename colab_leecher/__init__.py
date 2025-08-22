#================================================
#FILE: colab_leecher/__init__.py
#================================================
# copyright 2023 © Xron Trix | https://github.com/Xrontrix10

import logging, json
# Attempt to import uvloop.  Not all environments provide this
# optional dependency.  If import fails the ``install`` function is
# replaced with a no‑op so that the rest of the module can continue
# without raising an exception.  When uvloop is unavailable the
# fallback logs a warning and leaves the default event loop in place.
try:
    from uvloop import install  # type: ignore
except Exception:
    def install() -> None:
        """Fallback when uvloop is unavailable.

        This dummy function allows the application to run even if
        ``uvloop`` is not installed in the runtime environment.  When
        called it simply logs a warning and returns immediately.
        """
        logging.getLogger(__name__).warning(
            "uvloop is not installed; proceeding with default event loop."
        )
from pyrogram.client import Client
# --- ADDED: Import BOT object to set settings ---
from .utility.variables import BOT
# --- END ADDED ---

# Set up logging
logging.basicConfig(
     level=logging.INFO,
     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__) # Use a logger instance


# Load credentials from a JSON file or environment variables.
credentials: dict[str, str | int] = {}

# Determine credentials file path.  Prefer the ``CREDENTIALS_PATH`` environment
# variable if set, otherwise look for a ``credentials.json`` file in the
# repository root (one directory above this ``__init__.py``) as a
# fallback.  This logic avoids hard‑coded absolute paths and allows the
# bot to run in arbitrary environments.
import os as _os

default_creds_path = _os.path.join(_os.path.dirname(__file__), "..", "credentials.json")
credentials_path = _os.environ.get("CREDENTIALS_PATH", default_creds_path)

try:
    with open(credentials_path, "r", encoding="utf-8") as file:
        credentials = json.load(file)
    log.info(f"Credentials loaded from {credentials_path}.")
except FileNotFoundError:
    log.warning(f"Credentials file not found at {credentials_path}. Falling back to environment variables.")
    credentials = {}
except json.JSONDecodeError as e:
    log.error(f"Failed to parse credentials file {credentials_path}: {e}. Falling back to environment variables.")
    credentials = {}
except Exception as e:
    log.error(f"Unexpected error loading credentials: {e}. Falling back to environment variables.", exc_info=True)
    credentials = {}


# --- Assign credentials to variables ---
def _get_cred(key: str, default: str | int | None = None) -> str | int | None:
    """Helper to return a credential from the JSON file or environment."""
    if key in credentials and credentials[key] not in (None, ""):
        return credentials[key]
    return _os.environ.get(key, default)

# Required credentials.  If a value is missing, ``None`` will be returned.
raw_api_id = _get_cred("API_ID")
API_ID = int(raw_api_id) if raw_api_id not in (None, "") else None
API_HASH = _get_cred("API_HASH")
BOT_TOKEN = _get_cred("BOT_TOKEN")
raw_owner = _get_cred("USER_ID")
OWNER = int(raw_owner) if raw_owner not in (None, "") else None
raw_dump = _get_cred("DUMP_ID")
DUMP_ID = int(raw_dump) if raw_dump not in (None, "") else None

# Validate required credentials and abort early if any are missing.
missing_required = [k for k, v in {"API_ID": API_ID, "API_HASH": API_HASH, "BOT_TOKEN": BOT_TOKEN, "USER_ID": OWNER, "DUMP_ID": DUMP_ID}.items() if not v]
if missing_required:
    log.critical(f"Missing required credentials: {', '.join(missing_required)}.\n"
                 "Please provide them via credentials.json or environment variables.")
    raise SystemExit(f"Missing required credentials: {', '.join(missing_required)}")


# --- MODIFICATION: Load Optional Cookies and set them in BOT.Setting ---
log.info("Loading optional downloader cookies...")
BOT.Setting.nzb_cf_clearance = _get_cred("NZBCLOUD_CF_CLEARANCE", "")
BOT.Setting.bitso_identity_cookie = _get_cred("BITSO_IDENTITY_COOKIE", "")
BOT.Setting.bitso_phpsessid_cookie = _get_cred("BITSO_PHPSESSID_COOKIE", "")

# Optional SABnzbd and NZBHydra API settings.  These values are used by
# integration modules if you choose to enable SABnzbd uploads or NZB searches.
BOT.Setting.sabnzbd_api_key = _get_cred("SABNZBD_API_KEY", "")
BOT.Setting.sabnzbd_url = _get_cred("SABNZBD_URL", "")
BOT.Setting.hydra_api_key = _get_cred("HYDRA_API_KEY", "")
BOT.Setting.hydra_url = _get_cred("HYDRA_URL", "")

log.info(f"NZBCloud CF Cookie: {'Set' if BOT.Setting.nzb_cf_clearance else 'Not Set'}")
log.info(f"Bitso Identity Cookie: {'Set' if BOT.Setting.bitso_identity_cookie else 'Not Set'}")
log.info(f"Bitso PHPSESSID Cookie: {'Set' if BOT.Setting.bitso_phpsessid_cookie else 'Not Set'}")
# --- END MODIFICATION ---


# Install uvloop
try:
     install()
     log.info("uvloop installed.")
except Exception as e:
     log.warning(f"Could not install uvloop: {e}")

# Initialize Pyrogram Client
try:
    log.info("Initializing Pyrogram client...")
    # Initialize Pyrogram Client - REMOVED retry_delay and sleep_threshold
    colab_bot = Client(
        "colab_bot", # Session name
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        # --- Keep only valid parameters ---
        workers=16  # Increase worker threads (default is 4)
        # --- Removed retry_delay=1 ---
        # --- Removed sleep_threshold=10 ---
    )
    log.info("Pyrogram client initialized.")
    # ... (rest of the __init__.py) ...

except Exception as e:
    log.critical(f"Failed to initialize Pyrogram client: {e}", exc_info=True)
    colab_bot = None 
