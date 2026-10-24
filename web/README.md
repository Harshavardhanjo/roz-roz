# Roz Roz — web app

Next.js (App Router, TypeScript, Tailwind) app for the owner/roommate side of Roz Roz. Talks to the FastAPI
backend in the repo root over its contract-2 web API (`../docs/CHANGES_FOR_TEAM.md` has the full contract and the
deltas since the LLD).

## Run locally

```bash
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE_URL
npm install
npm run dev
```

Needs the backend running separately (`USE_STUBS=true` works with no database — see the repo root README). The
backend's `WEB_ORIGIN` must include `http://localhost:3000` (its default) or CORS blocks every request.

## How it's wired

| Path | Purpose |
|---|---|
| `lib/api.ts` | Typed client for every contract-2 endpoint. Sends `X-Roz-Token`; throws `ApiError` on the backend's `{"error": {"code", "message"}}` shape |
| `lib/types.ts` | Response types mirroring `app/services/views.py` / `app/stubs.py` in the backend |
| `lib/session.ts`, `lib/MeContext.tsx` | Resolves a member's magic-link token via `GET /api/me`; shares it to child pages via context |
| `app/h/[token]/` | Everything behind a flat's magic link: dashboard, payments (the mock top-up flow), votes, audit |

No real money moves anywhere in this app — every payment is simulated by the backend's `SimulatedProvider`, and
the UI says so.
