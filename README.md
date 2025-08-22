# Colab Leecher – Refactored

This repository contains a refactored version of the Colab Leecher bot.  The
primary objectives of this refactor are to remove hard‑coded credentials,
eliminate unsafe uses of shell commands, fix logical bugs, and make the
project easier to run outside of the Google Colab environment.

## Key Improvements

* **No hard‑coded secrets:** All API keys, bot tokens and chat IDs are now
  loaded from a ``credentials.json`` file or the process environment rather
  than being embedded in the source code.  A sample file is provided as
  ``credentials.example.json``.
* **Safer archive creation:** The archive utility now uses Python’s
  ``zipfile`` module instead of invoking ``7z`` via ``subprocess``, which
  avoids command‑injection vulnerabilities and external dependencies.  Archive
  splitting is not currently supported.
* **Simplified entrypoint:** The Colab‑specific ``main.py`` has been
  deprecated.  To run the bot you simply execute ``python -m colab_leecher``
  after installing the requirements and configuring your credentials.
* **Bug fixes:** Undefined variables and other logical errors have been
  addressed, such as the ``spotify_url`` ``NameError`` previously present in
  the ``/tupload`` handler.

## Installation

1.  Clone or download this repository.
2.  Create and activate a Python virtual environment (optional but
    recommended).
3.  Install the dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4.  Copy ``credentials.example.json`` to ``credentials.json`` and replace the
    placeholder values with your own API credentials.  You can also set the
    same values as environment variables; the bot will prefer environment
    variables over the JSON file.

5.  Start the bot:

    ```bash
    python -m colab_leecher
    ```

The bot uses the Pyrogram library under the hood, so the first time it
runs it will create a session file in the repository directory.  Follow
the on‑screen prompts to authenticate your bot account.

## Configuration File

The credentials JSON file should have the following structure:

```json
{
  "API_ID": 0,
  "API_HASH": "",
  "BOT_TOKEN": "",
  "USER_ID": 0,
  "DUMP_ID": 0,
  "NZBCLOUD_CF_CLEARANCE": "",
  "BITSO_IDENTITY_COOKIE": "",
  "BITSO_PHPSESSID_COOKIE": "",
  "SABNZBD_API_KEY": "",
  "SABNZBD_URL": "",
  "HYDRA_API_KEY": "",
  "HYDRA_URL": ""
}
```

If any of the above keys are missing from the JSON file, the bot will
attempt to read the corresponding environment variable instead.  All
credentials are optional except for ``API_ID``, ``API_HASH``, ``BOT_TOKEN``
and ``USER_ID``/``DUMP_ID`` which are required for the bot to operate.

## Caveats

* The legacy Colab automation pipeline has been removed.  Running this bot
  now requires a standard Python environment.  For Google Colab users,
  manually upload the repository and run the same commands in a Colab
  notebook cell.
* Some advanced features from the original project (such as archive
  splitting, certain debrid services and experimental commands) may have
  been disabled or simplified in the interest of security and stability.

## License

This refactor preserves the original license.  See ``LICENSE`` for
details.