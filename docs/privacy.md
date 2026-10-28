# Privacy and security

## Where data goes

The server runs on your computer over stdio. It calls Google's Health API with your authorization and returns the response to the requesting MCP client. It does not send data to a project-operated service, include telemetry, or cache health responses on disk. TCX exports are returned to the client rather than saved automatically.

Your agent, model provider, conversation history, and any client-side logging can retain tool results under their own settings. This server cannot enforce those policies. For processing confined to your computer, use a local MCP client and model. Google remains the source of the health data.

## Local credentials

OAuth client configuration and tokens are saved in the platform-specific `ghealth` user configuration directory, outside your checkout. `ghealth-mcp status` shows that location without printing tokens. Downloaded client JSON files should be kept private and outside Git.

On Windows, setup and agents share `%LOCALAPPDATA%\ghealth\ghealth`. If an agent reports missing configuration after you signed in, check that it can access this folder before repeating setup.

- `auto` (default) saves tokens to a private local file and makes a best-effort copy to the OS keyring, supporting agents that cannot access the keyring. The file is authoritative so failed keyring updates cannot silently select an old account. An unreadable or corrupt file does not fall back to potentially stale keyring credentials.
- `keyring` keeps tokens only in the OS credential store. Choose it with `ghealth auth configure --token-storage keyring` and sign in again. It requires every agent to have access to that store.
- `plaintext` uses only the local file and requires explicit acknowledgement in the CLI configuration command.

After logout, automatic storage keeps an empty private marker so an unavailable keyring cannot restore an older sign-in.

Credential files and agent configuration edits use unique temporary files and atomic replacement. POSIX files start with owner-only permissions; Windows files inherit their directory ACLs. Use a private OS user account and user directory. This does not protect against malware or another process running as you.

## OAuth and tools

Each user brings their own Google Desktop OAuth client. Sign-in uses PKCE, random state validation, and a loopback callback bound to `127.0.0.1`. OAuth endpoints are restricted to Google. Token refresh is automatic. Credentials are never returned by MCP tools or inserted into agent configuration.

MCP tools preserve Google's structured JSON fields and pagination tokens. Each list call fetches one page; agents should request narrow date ranges and follow `nextPageToken` as `page_token`. Returned records are data, including any user-authored text. They should not be treated as instructions.

The server exposes read tools by default. Mutations require both `serve --allow-writes` and Google's corresponding write scopes. MCP annotations describe destructive operations but do not replace the agent's approval controls.

## Troubleshooting and disconnecting

- Run `ghealth-mcp setup` to renew sign-in. Browser consent waits up to ten minutes.
- For a redirect mismatch, import a **Desktop app** client JSON with `setup --credentials`.
- If Google shows an unverified-app notice, review your developer account and requested permissions before deciding whether to continue. The displayed name comes from Google Cloud branding and can still be `ghealth-cli` after a repository rename.
- For access-denied errors, check API enablement, consent-screen test users, and approved scopes in your Google Cloud project.
- Google's [refresh token limits](https://developers.google.com/identity/protocols/oauth2#expiration) can require renewed consent for external apps in Testing status.
- `ghealth-mcp logout` revokes Google's grant, then deletes local tokens. If revocation fails, tokens remain available so you can retry. Storage deletion errors are reported rather than claiming success. You can also remove the grant through your Google Account's connected-app settings.

See Google's [Health setup guide](https://developers.google.com/health/setup) and [Desktop OAuth documentation](https://developers.google.com/identity/protocols/oauth2/native-app).
