"""A small client for the callyour.ai API, and where the API key lives."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_API_URL = "https://api.callyour.ai"


class CallyouraiError(ToolError):
    """An error answer of the API, with its hint for what to do next. A ToolError, so the agent sees the text."""

    def __init__(self, status: int, code: str, message: str, next_hint: Any = None) -> None:
        self.status, self.code, self.next_hint = status, code, next_hint
        text = f"{message} (HTTP {status}, {code})"
        if next_hint:
            text += f"\nNext: {json.dumps(next_hint)}"
        super().__init__(text)


def credentials_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "callyourai" / "credentials.json"


def load_key() -> str | None:
    """The API key: ``CALLYOURAI_API_KEY`` first, then the file ``sign_up`` wrote."""
    key = os.environ.get("CALLYOURAI_API_KEY")
    if key:
        return key.strip()
    path = credentials_path()
    try:
        return json.loads(path.read_text()).get("api_key") or None
    except (OSError, ValueError):
        return None


def save_key(api_key: str, account_id: str) -> Path:
    """Store the key for later sessions, readable by this user only."""
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"api_key": api_key, "account_id": account_id}, indent=2) + "\n")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)
    return path


class Api:
    def __init__(self, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = (base_url or os.environ.get("CALLYOURAI_API_URL") or DEFAULT_API_URL).rstrip("/")
        self._transport = transport

    async def call(self, method: str, path: str, body: dict | None = None, *, auth: bool = True) -> Any:
        headers = {"user-agent": "callyourai-mcp"}
        if auth:
            key = load_key()
            if not key:
                raise CallyouraiError(
                    401, "no_api_key", "No callyour.ai API key yet.",
                    {"tool": "sign_up", "why": "Creates an account and stores its key; or set CALLYOURAI_API_KEY."},
                )
            headers["authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(base_url=self.base_url, timeout=120, transport=self._transport) as http:
            response = await http.request(method, path, json=body, headers=headers)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            error = (data or {}).get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                raise CallyouraiError(response.status_code, error.get("code", "error"),
                                      error.get("message", response.text[:300]), error.get("next"))  # fmt: skip
            raise CallyouraiError(response.status_code, "error", response.text[:300])
        return data
