"""
Web server for Telegram‑Leecher‑Gemini.

This package exposes a simple FastAPI application that can be run
alongside the bot to serve status information or provide a basic
health check endpoint.  The upstream project offered a more
extensive dashboard; here we only implement a minimal root
endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Telegram‑Leecher‑Gemini Web UI")


@app.get("/")
async def root() -> dict[str, str]:
    """Return a simple status message."""
    return {"status": "Telegram‑Leecher‑Gemini web interface running"}


def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Run the FastAPI application using uvicorn.

    This function blocks until the server is stopped.  It is intended
    to be called in a dedicated thread so as not to interfere with
    the main event loop used by the bot.
    """
    import uvicorn
    uvicorn.run(app, host=host, port=port)


__all__ = ["app", "run_server"]