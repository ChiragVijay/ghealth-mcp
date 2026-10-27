# G Health MCP

Connect your Google Health data to Codex, Cursor, Claude Code, or Claude Desktop. Ask about workouts, sleep, daily activity, and other measurements available through the Google Health API.

Unofficial project; not affiliated with Google.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run this from the project folder:

```sh
uv tool install .
```

Requires Python 3.13 or newer. uv can install Python for you.

## Set up Google access

Each user needs their own Google OAuth client. Follow Google's [Health API setup guide](https://developers.google.com/health/setup) to:

1. Create a Google Cloud project and enable the Google Health API.
2. Configure the consent screen, add your account as a test user, and select the Health API scopes you need.
3. Create a **Desktop app** OAuth client and download its JSON file. Choose Desktop app rather than the Web Server option in Google's generic wizard.

Keep the downloaded file private.

## Sign in and connect your agent

Install your chosen agent, then run:

```sh
ghealth-mcp setup --credentials "/path/to/client.json" --client codex
```

Choose the client name for your agent:

| Agent | Client name |
| --- | --- |
| Codex | `codex` |
| Cursor | `cursor` |
| Claude Code | `claude` |
| Claude Desktop | `claude-desktop` |

For Kiro Crew, follow the [manual setup](docs/clients.md#kiro-crew).

Approve access in your browser, then restart or reconnect your agent. Your sign-in is saved and refreshed automatically.

To connect another agent using the same sign-in:

```sh
ghealth-mcp connect --client cursor
```

See [manual configuration](docs/clients.md) if you need to edit your agent's settings yourself.

## Use it

Ask your agent:

- “Show my daily steps for the last week.”
- “Summarize my latest workout.”
- “How much deep sleep did I get last night?”

Available data depends on your device, Google permissions, and what the API exposes. Access is read-only by default.

Run `ghealth-mcp status` to check your connection, `ghealth-mcp setup` to sign in again, or `ghealth-mcp logout` to disconnect.

## Privacy

Credentials stay on your computer. The server fetches data from Google and returns it to your agent without caching health records or sending them to a project-operated service. Your agent and its model provider can see the returned data.

More: [privacy and troubleshooting](docs/privacy.md) · [optional CLI](docs/cli.md).
