# AI Holdem Coach — Ops notes

Quick reference for operating this app. Owner is non-technical; changes are made
by an AI coding assistant, committed to `main`, auto-deployed by Vercel.

## Stack
- Hosting: Vercel (`https://aiholdemcoach.vercel.app`) — deploys from `main`.
- Database: Supabase project `gqzyvfjcfgmocknrnxob`.
- AI: Groq (`openai/gpt-oss-120b`), Treys for hand evaluation.
- Frontend is a plain HTML/JS PWA (`public/`); no build step.

## Vercel environment variables (dashboard)
| Var | Purpose |
| --- | --- |
| `GROQ_API_KEY` | AI calls |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Server-only DB key (bypasses RLS, never in browser) |
| `DISCORD_WEBHOOK_URL` | Error/signup notifications channel |
| `DISCORD_SHARE_WEBHOOK_URL` | "Share my latest night" target channel |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | Discord OAuth account linking only |
| `CHAT_DAILY_LIMIT` | Per-user coach replies/day (default `300`) |
| `CHAT_GLOBAL_DAILY_LIMIT` | Global replies/day cost backstop (default `3000`) |
| `CHAT_WHITELIST` | Comma-separated emails exempt from the per-user cap (owner's email) |

## Supabase SQL
New tables/functions live in `supabase/schema.sql`. The human runs new blocks
manually in the Supabase SQL editor — the app fail-opens (one Discord ping) until
they're applied.

- `chat_usage` + `bump_chat_usage(day,user,global)` = daily per-user/global counters.
  Only the service key may call it; anon/authenticated are revoked.
- All data tables have RLS with no policies; all access goes through the backend.

## Pushing changes when git is broken
`git` on this Mac fails (Xcode license), so commits go via GitHub Contents API
with a PAT from the macOS keychain (login `marshtate`, 40 chars):
`security find-internet-password -s github.com -w` — the macOS approval prompt
sometimes hangs; it was approved this session.
GET file `sha` → PUT base64 content with `sha` + `branch: main`.

## Deployment verification
```
curl https://aiholdemcoach.vercel.app/api/discord/widget   # {ok,name,presence_count,invite}
```
Clients may need a double reload (service worker cache `aihc-v2`; `/api/*` is
never intercepted).

## Discord
- Community server "Holdem Coach", guild ID `1549096373977354271`.
- Server widget: `https://discord.com/api/guilds/1549096373977354271/widget.json`
  (feed = presence + `instant_invite`). Backend `/api/discord/widget` proxies it.
- Fallback invite shown in app: `https://discord.gg/KB4rNwnea`.

## Key files
- `api/index.py` — all backend endpoints (serverless FastAPI on Vercel).
- `public/app.js` — single-page frontend logic.
- `public/index.html` — markup, settings modal, auth screen.
- `supabase/schema.sql` — manual SQL migrations.

## Test scripts (in macOS tmpdir)
- `share_test.py` — Discord share-flow e2e. `e2e.py` — app regression.
  `stress.py` — multi-hand logging reliability. `rls_probe*.py` — RLS audit.

## Notes / gotchas
- Throwaway test users accumulate in the real DB (harmless).
- Python 3.14 on this Mac has no CA certs — test scripts use an unverified SSL context.
- Units setting is per-device (localStorage); a future "sync" would move it server-side.