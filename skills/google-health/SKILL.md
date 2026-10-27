---
name: google-health
description: Use the ghealth CLI to inspect Google Health data. Use when asked to check Google Health auth/scopes, discover data types, list devices, fetch steps, sleep, heart-rate, weight, calories, or manage Google Health webhook infrastructure.
---

# Google Health CLI

When the `ghealth-mcp` server is connected, prefer its native tools. Start with
`list_data_types`, use reconciled records or rollups for totals, and preserve
Google's response fields. If sign-in is needed, have the user run `ghealth-mcp setup`
in their terminal. The CLI commands below remain available as a fallback.

Use `ghealth` for local, user-authorized Google Health API data. Prefer `--format json`.
In a source checkout where `ghealth` is not installed, prefix commands with `uv run`.

## Safety

- Fetch the narrowest date range possible.
- Use `--limit` when exploring unknown list data.
- Prefer read-only commands.
- Do not create, update, delete, export large files, or revoke auth unless the user explicitly asks.
- Do not send raw health data to external services unless the user asks.

## Start

```bash
ghealth --format json doctor
```

If `doctor` needs more auth detail:

```bash
ghealth --format json auth status
```

Ask before logging in or changing scopes:

```bash
ghealth auth login
```

For read commands plus webhooks in one token, use:

```bash
ghealth auth login --with-webhooks
```

## Read Commands

```bash
ghealth --format json steps daily --last-days 5
ghealth --format json calories daily --last-days 5
ghealth --format json active-energy daily --last-days 5
ghealth --format json active-minutes daily --last-days 5
ghealth --format json active-zone-minutes daily --last-days 5
ghealth --format json distance daily --last-days 5
ghealth --format json floors daily --last-days 5
ghealth --format json sleep list --start 2026-06-01 --end 2026-06-10 --limit 25
ghealth --format json heart-rate list --start 2026-06-01T00:00:00Z --end 2026-06-02T00:00:00Z --limit 100
ghealth --format json exercise list --start 2026-06-01 --end 2026-06-10 --limit 25
ghealth --format json weight list --start 2026-01-01 --end 2026-06-10 --limit 25
ghealth --format json height list --start 2026-01-01 --end 2026-06-10 --limit 25
ghealth --format json body-fat list --start 2026-01-01 --end 2026-06-10 --limit 25
ghealth --format json hydration list --start 2026-06-01 --end 2026-06-10 --limit 25
ghealth --format json food list --limit 25
ghealth --format json nutrition list --start 2026-06-01 --end 2026-06-10 --limit 25
ghealth --format json devices list --limit 25
ghealth --format json user profile
```

## Discovery

Use discovery for unfamiliar data types or generic data-point commands.

```bash
ghealth --format json data-types list
ghealth --format json data-types describe steps
ghealth --format json data-types operations steps
ghealth --format json auth scopes
ghealth --format json examples
ghealth --format json data-points list DATA_TYPE --start START --end END --limit 25
ghealth --format json data-points daily-rollup DATA_TYPE --last-days 5
```

## Command List

Read shortcuts: `steps daily`, `calories daily`, `active-energy daily`, `active-minutes daily`,
`active-zone-minutes daily`, `distance daily`, `floors daily`, `sleep list`, `heart-rate list`,
`exercise list`, `weight list`, `height list`, `body-fat list`, `hydration list`, `food list`,
`nutrition list`, `devices list`, `user profile`.

Other read commands: `doctor`, `auth status`, `auth scopes`, `examples`, `user identity`,
`user settings`, `devices get`, `data-types list`, `data-types describe`, `data-types operations`,
`data-types scopes`, `data-points list`, `data-points get`, `data-points reconcile`,
`data-points rollup`, `data-points daily-rollup`.

## Webhooks

Webhook commands manage infrastructure and require `cloud-platform` scope plus a public HTTPS endpoint.

```bash
ghealth --format json subscribers list --project PROJECT_ID --limit 25
ghealth --format json subscriptions list --subscriber projects/PROJECT_ID/subscribers/SUBSCRIBER_ID --limit 25
```

## Write/Delete Rules

Only run these after explicit user confirmation:

```bash
ghealth data-points create DATA_TYPE --body data-point.json --yes
ghealth data-points update DATA_POINT_NAME --body data-point.json --yes
ghealth data-points batch-delete DATA_TYPE --name DATA_POINT_NAME --yes
ghealth subscribers delete SUBSCRIBER_NAME --yes
ghealth subscriptions delete SUBSCRIPTION_NAME --yes
ghealth auth revoke
```

If JSON or noninteractive mode returns `confirmation_required`, stop and ask the user.

## Troubleshooting

- `not_configured`: ask for Google OAuth credentials, then run `ghealth auth configure --credentials PATH`.
- `not_authenticated`: ask before running `ghealth auth login`.
- `missing_scope_or_forbidden`: show the suggested login command from error details.
