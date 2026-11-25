"""The callyour.ai MCP server: sign up, pay, create avatars, render videos and wire up the LiveKit plugin from a
coding agent. Runs over stdio:

    uvx callyourai-mcp
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .api import Api, CallyouraiError, credentials_path, save_key

INSTRUCTIONS = """callyour.ai gives LiveKit voice agents a real-time talking face, and renders avatar videos from audio.
Typical order: sign_up (once) -> buy_credits (hand the URL to the human) -> create_avatar from a photo ->
setup_livekit_agent for live calls, or render_video for an MP4. Credits are prepaid euros, billed per second.
Full guide: https://api.callyour.ai/llms.txt"""

LIVEKIT_SNIPPET = """from livekit.agents import AgentSession, room_io
from livekit.plugins import callyourai

async def entrypoint(ctx):
    await ctx.connect()
    session = AgentSession(stt=..., llm=..., tts=...)
    avatar = callyourai.AvatarSession(avatar_id="{avatar_id}")   # reads CALLYOURAI_API_KEY
    await avatar.start(session, room=ctx.room)                    # before session.start
    await session.start(agent=MyAgent(), room=ctx.room,
                        room_options=room_io.RoomOptions(audio_output=False))"""

MAX_FILE_BYTES = 40 * 2**20

server = MCPServer(
    name="callyourai",
    title="callyour.ai avatars",
    instructions=INSTRUCTIONS,
    website_url="https://callyour.ai",
)
api = Api()


def _file_base64(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        raise ToolError(f"No such file: {file}")
    if file.stat().st_size > MAX_FILE_BYTES:
        raise ToolError(f"{file} is larger than {MAX_FILE_BYTES // 2**20} MB.")
    return base64.b64encode(file.read_bytes()).decode()


async def _poll(path: str, done: tuple[str, ...], timeout_s: float, every_s: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        item = await api.call("GET", path)
        if item.get("status") in done or time.monotonic() >= deadline:
            return item
        await asyncio.sleep(every_s)


@server.tool()
async def sign_up(email: str, account_name: str | None = None) -> dict:
    """Create a callyour.ai account and get an API key. No browser and no email confirmation needed.

    The key is shown once: it is saved to ~/.config/callyourai/credentials.json (readable only by you), and
    you should also put it into the project's environment as CALLYOURAI_API_KEY (for example in .env).
    """
    body = {"email": email} | ({"account_name": account_name} if account_name else {})
    result = await api.call("POST", "/v1/signup", body, auth=False)
    path = save_key(result["api_key"], result["account_id"])
    return {
        "account_id": result["account_id"],
        "api_key": result["api_key"],
        "saved_to": str(path),
        "do_next": "Add CALLYOURAI_API_KEY=<api_key> to the project's .env (never commit it), then buy_credits.",
        "balance": result.get("balance", result.get("balance_usd")),
        "currency": result.get("currency", "EUR"),
    }


@server.tool()
async def get_balance() -> dict:
    """The account's credit balance in euros, the price per minute of each avatar tier, and the credit packs."""
    return await api.call("GET", "/v1/balance")


@server.tool()
async def buy_credits(amount: float | None = None, pack: str | None = None) -> dict:
    """Create a payment page for prepaid credits. Give amount in euros (5 to 10000) or a pack id from get_balance.

    Returns checkout_url: open it or hand it to the human who pays. The balance rises a few seconds after
    payment; check with get_balance. Bigger purchases get bonus credit.
    """
    if (amount is None) == (pack is None):
        raise ToolError("Give exactly one of amount (euros) or pack.")
    body = {"amount": amount} if amount is not None else {"pack": pack}
    return await api.call("POST", "/v1/credits/checkout", body)


@server.tool()
async def create_avatar(
    name: str,
    image_url: str | None = None,
    image_path: str | None = None,
    tier: Literal["premium", "standard"] = "premium",
    wait_seconds: int = 120,
) -> dict:
    """Create a talking avatar from one photo: one face, frontal, head and shoulders, even light, nothing covering
    the face. Give image_url (public) or image_path (a local file). Waits until the avatar is ready (about 30 s)
    and returns its id; if it is still processing after wait_seconds, poll list_avatars later.
    """
    if (image_url is None) == (image_path is None):
        raise ToolError("Give exactly one of image_url or image_path.")
    body: dict = {"name": name, "tier": tier}
    if image_url:
        body["image_url"] = image_url
    else:
        body["image_base64"] = _file_base64(image_path)
    created = await api.call("POST", "/v1/avatars", body)
    avatar = await _poll(f"/v1/avatars/{created['id']}", ("ready", "failed"), max(0, min(wait_seconds, 600)))
    return avatar


@server.tool()
async def list_avatars() -> dict:
    """The account's avatars with id, name, tier and status (processing, ready or failed)."""
    return await api.call("GET", "/v1/avatars")


@server.tool()
async def render_video(
    avatar_id: str,
    audio_url: str | None = None,
    audio_path: str | None = None,
    quality: Literal["standard", "high"] = "standard",
    wait_seconds: int = 300,
) -> dict:
    """Render the avatar speaking an audio file (WAV, MP3, M4A, OGG or FLAC, up to 10 minutes) as an MP4.
    Give audio_url (public) or audio_path (a local file). Billed per second of finished video. Waits until it is
    ready and returns download_url (valid one hour; the file is kept 7 days). quality "standard" (384 px) is ready
    in about 1.5x the audio length; "high" (512 px, more detail) waits for a gap between live calls and then takes
    about 6x the audio length, so pass a larger wait_seconds for it, or call get_video later with the returned id.
    """
    if (audio_url is None) == (audio_path is None):
        raise ToolError("Give exactly one of audio_url or audio_path.")
    body: dict = {"avatar_id": avatar_id, "quality": quality}
    if audio_url:
        body["audio_url"] = audio_url
    else:
        body["audio_base64"] = _file_base64(audio_path)
    created = await api.call("POST", "/v1/videos", body)
    return await _poll(f"/v1/videos/{created['id']}", ("ready", "failed"), max(0, min(wait_seconds, 1800)), 5.0)


@server.tool()
async def get_video(video_id: str) -> dict:
    """The current state of a rendered video: status (queued, rendering, ready, failed), queue_position while
    queued, and download_url once ready."""
    return await api.call("GET", f"/v1/videos/{video_id}")


@server.tool()
async def get_usage() -> dict:
    """Recent live sessions with billed seconds and euros, and the account's purchases."""
    return await api.call("GET", "/v1/usage")


@server.tool()
async def setup_livekit_agent(avatar_id: str | None = None) -> dict:
    """How to give a LiveKit Agents voice agent this avatar: the install command, the environment variables and
    the code to add. Start the avatar before the agent session and switch the agent's own audio output off."""
    return {
        "install": "pip install livekit-plugins-callyourai",
        "environment": ["CALLYOURAI_API_KEY", "LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"],
        "code": LIVEKIT_SNIPPET.format(avatar_id=avatar_id or "YOUR_AVATAR_ID"),
        "notes": [
            "The avatar joins the room as participant 'callyourai-avatar'; frontends show its video and play its audio.",
            "avatar.start raises callyourai.CallyouraiError with .code insufficient_credits, no_capacity, conflict "
            "(avatar not ready) or not_found.",
            "A lost GPU worker is replaced automatically; the plugin emits avatar_lost and avatar_recovered.",
        ],
        "guide": "https://api.callyour.ai/llms.txt",
        "key_file": str(credentials_path()),
    }


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        server.run("stdio")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


__all__ = ["server", "main", "CallyouraiError"]
