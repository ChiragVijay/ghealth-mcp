# Optional CLI

The package also installs `ghealth` for direct terminal use. Use the [main setup guide](../README.md) to install and sign in; the CLI and MCP share the same local credentials.

```sh
ghealth --help
ghealth --format json doctor
ghealth steps daily --last-days 5
ghealth sleep list --limit 10
ghealth heart-rate list --limit 20
ghealth weight list --limit 5
ghealth exercise list --limit 5
```

Use `--format json` to preserve API response fields. The CLI also includes data-point mutations and webhook administration; run each command's `--help` for arguments. Mutations require the corresponding Google scopes and explicit confirmation.

The optional [agent skill](../skills/google-health/SKILL.md) documents CLI fallback workflows. Prefer native MCP tools when the server is connected.

## Updates

Stop connected agents' MCP processes before updating, especially on Windows where a running Python executable can prevent environment replacement. From an updated checkout:

```sh
uv tool install --force .
```

Then reconnect your agents. Credentials are stored outside the installation and are retained.
