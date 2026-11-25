# callyourai-mcp

An MCP server for [callyour.ai](https://callyour.ai): your coding agent can sign up, buy credits, create a
real-time talking avatar from a photo, render avatar videos, and wire the avatar into a LiveKit voice agent,
without you opening a dashboard.

## Install

Claude Code:

```bash
claude mcp add callyourai -- uvx callyourai-mcp
```

Cursor (`.cursor/mcp.json`) or Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "callyourai": { "command": "uvx", "args": ["callyourai-mcp"] }
  }
}
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.callyourai]
command = "uvx"
args = ["callyourai-mcp"]
```

Needs [uv](https://docs.astral.sh/uv/). With an existing key, pass it in the environment:
`claude mcp add callyourai -e CALLYOURAI_API_KEY=... -- uvx callyourai-mcp`.

## Tools

| Tool | What it does |
|---|---|
| `sign_up(email, account_name?)` | Creates an account and returns an API key. The key is saved to `~/.config/callyourai/credentials.json` (mode 600). |
| `get_balance()` | Balance in euros, prices per minute, credit packs. |
| `buy_credits(amount \| pack)` | A payment page URL to open or hand to the person who pays. |
| `create_avatar(name, image_url \| image_path)` | Creates an avatar from one photo and waits until it is ready. |
| `list_avatars()` | The account's avatars and their status. |
| `render_video(avatar_id, audio_url \| audio_path, quality)` | Renders the avatar speaking an audio file; returns an MP4 download link. `quality`: `standard` (384 px), `high` (512 px, slower) or `studio` (768 px, slowest, audio up to 3 minutes). |
| `get_video(video_id)` | Status of a rendered video, and its download link once ready. |
| `get_usage()` | Recent sessions with billed seconds, and purchases. |
| `setup_livekit_agent(avatar_id?)` | The install command and code to give a LiveKit voice agent this avatar. |

The key is read from `CALLYOURAI_API_KEY` first, then from the credentials file. Errors include the API's
hint for what to do next, for example the checkout to make when credits run out.

## Try it

Ask your agent: *"Sign me up for callyour.ai with my email, create an avatar from ./me.jpg and add it to my
LiveKit agent."*

Full API guide: https://api.callyour.ai/llms.txt · Questions: support@callyour.ai

## Licence

MIT
