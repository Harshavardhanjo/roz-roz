# Roz Roz API

Household employee management for shared flats: helpers send WhatsApp voice notes; agents turn them into leave,
advance and grocery requests; house rules and each roommate's grant decide; payroll runs itself. **All payments are
simulated** (a ledger in Postgres; no real money moves).

Design: [Roz Roz: the pitch](https://claude.ai/artifact/Lr1br4adCW4XExHPchUxD8), tabs **Technical HLD** and **LLD**.
Changes to the contracts since the LLD: [docs/CHANGES_FOR_TEAM.md](docs/CHANGES_FOR_TEAM.md).

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                      # set DATABASE_URL to a local Postgres
.venv/bin/python -m scripts.migrate       # create tables (safe to re-run)
.venv/bin/python -m seed.demo_seed        # optional: load the demo flat, prints owner/roommate links
.venv/bin/uvicorn app.main:app --reload
```

No database? `USE_STUBS=true` serves the example payloads from `app/stubs.py` for every endpoint and tool.

## Deploy on Vercel

The backend runs as one Python serverless function (`api/index.py`, routed by `vercel.json`). The database stays on
Render Postgres.

1. Vercel → **Add New → Project** → import `Harshavardhanjo/roz-roz` (framework preset **Other**, root `./`).
2. Environment variables: `DATABASE_URL` (Render's **External** Database URL, as-is), `USE_STUBS=false`,
   `PUBLIC_BASE_URL` (the Vercel URL), `WEB_ORIGIN`, `TOOLS_TOKEN`, `ADMIN_TOKEN`, `CRON_SECRET`, and the WhatsApp /
   ElevenLabs keys when ready. Generate tokens with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Deploy, then check `https://<project>.vercel.app/health`.

On Vercel (`VERCEL=1` is set automatically) the app opens one database connection per request and skips the in-process
scheduler; Vercel Cron calls `GET /api/cron/payday` daily at 09:00 IST instead. Migrations don't run on deploy: run
`python -m scripts.migrate` with `DATABASE_URL` set before deploying a new migration.

## Tests

Integration tests run against a real Postgres; point `TEST_DATABASE_URL` at an empty database (it is wiped):

```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/rozroz_test .venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`tests/test_contract_shapes.py` fails if the real API stops returning a key the stubs promise; keep the stubs and the
LLD doc in step with any contract change.

## How it fits together

| Layer | Where | Notes |
|---|---|---|
| Web API (contract 2) | `app/routers/households.py`, `helpers.py`, `requests.py`, `ledger.py`, `audit.py`, `signups.py`, `admin.py` | Auth: `X-Roz-Token` (member link token). Errors: `{"error": {"code", "message"}}` |
| Agent tools (contract 3) | `app/routers/tools.py` | `Authorization: Bearer $TOOLS_TOKEN`; idempotent on `idempotency_key`; failures are `{"ok": false, ...}` |
| Rules | `app/services/rules.py`, `requests.py` | evaluate -> auto-approve / vote / needs top-up -> execute. `execute` refuses anything not approved |
| Leave, payroll, contributions | `app/services/leave.py`, `payroll.py`, `contributions.py` | Integer paise; IST dates; payroll is idempotent per helper and month |
| Grants | `app/services/grants.py` | Each member's limits for the agent, Grantex-style scopes, enforced locally |
| Payments | `app/providers/payment.py` | `SimulatedProvider` writes `ledger_entry` rows; swap for a real provider later |
| Treasurer | `app/services/treasurer.py` | Tries the agent when `AGENT_RUNTIME` is `local` / `agenticorg`, else runs the same steps in code |
| Audit | `app/services/audit.py` | Hash-chained; `audit.verify(db)` recomputes it |
| Payday | `app/services/scheduler.py` | 09:00 IST daily; run one web instance (the job is idempotent anyway) |
| Demo | `seed/demo_seed.py`, `POST /api/admin/reset-demo` (`X-Admin-Token`) | Rebuilds the documented demo state |

## Owners

| Path | Owner |
|---|---|
| `app/` except `voice/` and `agents/`, `migrations/`, `seed/`, `tests/` | Harsha |
| `app/voice/`, `app/agents/` | Divyansh |
| `web/` (Next.js app) | Venky |

Conventions: money is integer paise; IDs are UUIDv4; dates and months are IST (`YYYY-MM`); agents reach the database
only through `/tools/*`.
