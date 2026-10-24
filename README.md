# Roz Roz API

Household employee management for shared flats: helpers send WhatsApp voice notes; AgenticOrg agents turn them into
leave, advance and grocery requests; house rules and Grantex limits decide; payroll runs itself. All payments are
simulated in the demo.

Design: [Roz Roz: the pitch](https://claude.ai/artifact/Lr1br4adCW4XExHPchUxD8): tabs **Technical HLD** and **LLD**
(overview + one sub-tab per person). The three contracts in the LLD overview are frozen; change the doc first.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in what you have; USE_STUBS=true needs nothing else
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m pytest -q
```

With `USE_STUBS=true` every web endpoint and agent tool returns the contract 2 example payloads (`app/stubs.py`), so the
Next.js app and the agents can be built before the real services exist. Set `USE_STUBS=false` route by route as the real
code lands (endpoints still on stubs return 501 `not_implemented`).

Database: `python -m scripts.migrate` applies `migrations/*.sql` to `DATABASE_URL`.
Agent tool schemas: `python -m scripts.export_tool_schemas` writes `app/agents/tool_schemas.json` from `app/schemas.py`.

## Who owns what

| Path | Owner | State |
|---|---|---|
| `migrations/`, `app/models.py`, `app/schemas.py` | Harsha | Contracts 1 and 3 written |
| `app/routers/*` (web API), `app/routers/tools.py` | Harsha | Stubs live; real handlers TODO |
| `app/services/leave.py`, `payroll.py`, `rules.py`, `contributions.py`, `audit.py` | Harsha | Pure maths done and tested; DB-backed functions TODO |
| `app/providers/payment.py` | Harsha | In-memory `SimulatedProvider`; move to `ledger_entry` rows |
| `app/services/grantex_client.py`, `scheduler`, `seed/` reset | Harsha | TODO |
| `app/voice/` (WhatsApp webhook, client, ElevenLabs STT) | Divyansh | Verify + signature + parsing + clients written; `handle_inbound` TODO |
| `app/agents/` (prompts, templates, runtime, tools client) | Divyansh | Prompts and templates written; runtimes TODO |
| Next.js web app (separate repo) | Venky | Build on the stub API |

Conventions: money is integer paise; IDs are UUIDv4; times are IST; months are `YYYY-MM`. Agents reach the database
only through `/tools/*`.
