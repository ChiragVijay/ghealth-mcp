# Agent configuration

Prefer `ghealth-mcp connect --client codex` (or `cursor`, `claude`, `claude-desktop`). These manual examples are for custom configurations.

**Codex**, across its CLI and IDE:

```sh
codex mcp add ghealth -- ghealth-mcp
```

**Claude Code**, across projects:

```sh
claude mcp add --transport stdio --scope user ghealth -- ghealth-mcp
```

**Cursor:** merge into `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ghealth": {
      "type": "stdio",
      "command": "ghealth-mcp",
      "args": []
    }
  }
}
```

**Claude Desktop:** use the same JSON without `type` in `claude_desktop_config.json`, then restart. The file is in `%APPDATA%\Claude\` on Windows or `~/Library/Application Support/Claude/` on macOS.

If your app cannot find the executable, print config using this installation's **absolute Python path**:

```sh
ghealth-mcp config --client codex
ghealth-mcp config --client cursor
ghealth-mcp config --client claude
```

Merge Codex output into `~/.codex/config.toml`; the others produce `mcpServers` JSON. Config snippets contain no secrets. Restart or reconnect after editing configuration.

References: [Codex](https://developers.openai.com/codex/mcp), [Cursor](https://cursor.com/docs/mcp), [Claude Code](https://code.claude.com/docs/en/mcp), [Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

## Kiro Crew

1. Open **Customize → Connections → MCP Servers → Add Custom**.
2. Run `ghealth-mcp config --client claude` in your terminal and paste the resulting JSON into **Servers JSON**. This uses an absolute path to your installed server and includes no credentials.
3. Select **Enable immediately** and click **Add**.
4. Click **Apply & Restart** when your chats are idle, or start a new chat.

The server reuses your saved Google sign-in. Crew's Windows probe can report `mcp_probe_sandbox_unavailable` because Crew has no supported probe sandbox on that host. That message does not establish whether chat-side tool loading succeeded. Check the tools in a chat; do not disable sandbox protections merely to make the probe pass.

## Optional write access

Read access is the default. To create, update, or delete records, authorize the appropriate write scope and start `ghealth-mcp serve --allow-writes`. For example, retain reads and add activity writes:

```sh
ghealth-mcp setup --scopes activity_and_fitness.writeonly
```

Add `"serve", "--allow-writes"` to the agent's args (after `"-m", "ghealth.mcp_cli"` for generated configs). This exposes `create_data_point`, `update_data_point`, and `delete_data_points`, using Google's documented DataPoint JSON.
