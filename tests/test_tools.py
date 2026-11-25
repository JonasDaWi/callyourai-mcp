from __future__ import annotations

import json
import os
import stat

import httpx
import pytest
from mcp import Client

from callyourai_mcp import api as api_mod
from callyourai_mcp import server as srv


class FakeApi:
    """Answers like the live API for the calls the tools make."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict | None, str | None]] = []
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body, request.headers.get("authorization")))
        path = request.url.path
        if path == "/v1/signup":
            return httpx.Response(201, json={"api_key": "cyai_test_key", "account_id": "acc-1", "balance": 0, "currency": "EUR"})
        if path == "/v1/balance":
            return httpx.Response(200, json={"balance": 4.2, "currency": "EUR"})
        if path == "/v1/credits/checkout":
            if body.get("amount") == 1:
                return httpx.Response(422, json={"error": {"code": "bad_request", "message": "At least €5.",
                                                           "next": {"call": "GET /v1/balance"}}})
            return httpx.Response(200, json={"checkout_url": "https://pay.example/1", "pay": 10})
        if path == "/v1/avatars" and request.method == "POST":
            return httpx.Response(202, json={"id": "av-1", "status": "processing"})
        if path == "/v1/avatars/av-1":
            self.polls += 1
            return httpx.Response(200, json={"id": "av-1", "status": "ready" if self.polls > 1 else "processing"})
        if path == "/v1/videos" and request.method == "POST":
            return httpx.Response(202, json={"id": "v-1", "status": "rendering"})
        if path == "/v1/videos/v-1":
            return httpx.Response(200, json={"id": "v-1", "status": "ready", "download_url": "https://dl/v.mp4"})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "nope"}})


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fake = FakeApi()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("CALLYOURAI_API_KEY", raising=False)
    monkeypatch.setattr(srv, "api", api_mod.Api("https://api.test", httpx.MockTransport(fake.handler)))

    async def no_sleep(_):
        return None

    monkeypatch.setattr(srv.asyncio, "sleep", no_sleep)
    return fake


async def call(name: str, args: dict | None = None):
    async with Client(srv.server) as client:
        return await client.call_tool(name, args or {})


def payload(result) -> dict:
    return json.loads(result.content[0].text)


async def test_every_tool_is_listed_with_a_description():
    async with Client(srv.server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {"sign_up", "get_balance", "buy_credits", "create_avatar", "list_avatars",
                          "render_video", "get_video", "get_usage", "setup_livekit_agent"}
    assert all(t.description for t in tools.values())


async def test_sign_up_stores_the_key_privately_and_later_calls_use_it(fake, tmp_path):
    out = payload(await call("sign_up", {"email": "dev@example.com"}))
    path = tmp_path / "callyourai" / "credentials.json"
    assert out["saved_to"] == str(path) and json.loads(path.read_text())["api_key"] == "cyai_test_key"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert fake.requests[0][3] is None  # sign-up is unauthenticated
    await call("get_balance")
    assert fake.requests[-1][3] == "Bearer cyai_test_key"


async def test_without_a_key_the_tool_says_to_sign_up(fake):
    result = await call("get_balance")
    assert result.is_error and "sign_up" in result.content[0].text


async def test_api_errors_carry_the_next_hint(fake, monkeypatch):
    monkeypatch.setenv("CALLYOURAI_API_KEY", "k")
    result = await call("buy_credits", {"amount": 1})
    assert result.is_error and "GET /v1/balance" in result.content[0].text


async def test_create_avatar_from_a_local_file_waits_until_ready(fake, monkeypatch, tmp_path):
    monkeypatch.setenv("CALLYOURAI_API_KEY", "k")
    photo = tmp_path / "me.jpg"
    photo.write_bytes(b"\xff\xd8jpeg")
    out = payload(await call("create_avatar", {"name": "Me", "image_path": str(photo)}))
    assert out["status"] == "ready" and fake.requests[0][2]["image_base64"]


async def test_render_video_returns_the_download_link(fake, monkeypatch):
    monkeypatch.setenv("CALLYOURAI_API_KEY", "k")
    out = payload(await call("render_video", {"avatar_id": "av-1", "audio_url": "https://x/a.wav"}))
    assert out["download_url"] == "https://dl/v.mp4"


async def test_setup_livekit_agent_fills_in_the_avatar():
    out = payload(await call("setup_livekit_agent", {"avatar_id": "av-9"}))
    assert out["install"] == "pip install livekit-plugins-callyourai" and 'avatar_id="av-9"' in out["code"]
