# Setting up the Roz Roz agents in AgenticOrg

Create two custom agents in AgenticOrg's web UI (https://agenticorg.hackathon.pinelabs.com), then send back the two agent IDs.
Our API key can only run agents, not create them, so this step happens in the UI.

Everything to paste is in two files generated from the code:
- [`liaison.json`](liaison.json): the liaison agent, which turns a helper's message into requests.
- [`treasurer.json`](treasurer.json): the treasurer agent, which decides each new request.

Each file has the agent's name, system prompt, output schema and HTTP tools. If any of them changes, regenerate the
files with `python -m app.agents.agenticorg_setup`; a test fails when they drift.

## How a run works

1. When a helper's voice note arrives, our backend calls `POST /api/v1/agents/{agent_id}/run` with one JSON task. The task holds:
   - `instructions`: the full prompt for this message, with today's date and the helper's households.
   - `output_schema`: the shape of the final answer.
   - `transcript` (liaison) or `request_id` (treasurer).
   - `agent_run_id`.
   - `rules`: the idempotency key pattern.
2. The agent calls our tools at `https://roz-roz.vercel.app/tools/{name}`. Every call is a POST with the body
   `{"args": {...}, "idempotency_key": "...", "agent_run_id": "..."}` and gets back HTTP 200 with
   `{"ok": true, "result": ...}` or `{"ok": false, "error": {code, message}}`.
3. The agent finishes with one JSON object matching `output_schema`. Our backend builds the reply to the helper from
   the tool results, never from numbers the model writes.

Because the per-message instructions travel in the task, the system prompt in the UI stays short and never needs
editing when the rules change.

## Step by step (do it once per agent)

1. **Create a custom agent** named `Roz Roz liaison` (then `Roz Roz treasurer`).
2. **Model:** pick the fastest available (for example Claude Haiku). The treasurer has to finish in about 7.5 s.
3. **System prompt:** paste `system_prompt` from the JSON file.
4. **Output format:** if the UI has a JSON output or response-schema setting, paste `output_schema`. If it doesn't,
   skip this; the schema is already in each task.
5. **Tools:** add every entry under `tools` as an HTTP tool. The liaison has 6 tools and the treasurer has 6. For each:
   - **Name and description:** copy them as they are.
   - **Method and URL:** `POST https://roz-roz.vercel.app/tools/<name>`.
   - **Headers:** `Authorization: Bearer <TOOLS_TOKEN>` and `Content-Type: application/json`. Get `TOOLS_TOKEN` from
     Harsha (it is in the backend's Vercel env). Never paste it into git or chat.
   - **Input/body schema:** paste `input_schema`. The body sent must be exactly `{args, idempotency_key, agent_run_id}`.
6. **Limits:** if the UI allows, cap tool calls at `limits.max_tool_calls` (6 for the liaison, 4 for the treasurer).
7. **Approvals (treasurer only):** if the UI offers human approval (HITL) on a tool, do not turn it on for
   `execute_request`. The house rules already decide, and an approval pause would time the agent out. Votes go
   through `open_vote`.
8. **Save, and copy the agent's ID** (a UUID).

## Check it works before telling the team

Run this with the liaison's ID (replace `<LIAISON_ID>`). It should come back with `status: completed`. It only
asks for a balance, so no money moves. Get the key from `PINELAB_API_KEY` in your `.env`.

```bash
curl -s -X POST "https://agenticorg.hackathon.pinelabs.com/api/v1/agents/<LIAISON_ID>/run" -H "Authorization: Bearer $AGENTICORG_API_KEY" -H "Content-Type: application/json" -d '{"action":"process","inputs":{"task":"{\"instructions\":\"Call get_balances once for employment_id e9d20000-0000-4000-8000-000000000001, then answer {\\\"clarify\\\": null}.\",\"agent_run_id\":\"00000000-0000-4000-8000-000000000000\",\"rules\":\"Use idempotency_key setup-check:<n>\"}"},"context":{}}'
```

Then check the `tool_call` table (or ask Harsha) for a row with key `setup-check:0`. That row proves AgenticOrg
reached our tools with the right body. If the employment ID doesn't exist in the deployed database, the tool
answers `not_found`; that still proves the connection works.

## What to send back to Divyansh

| Item | Example |
|---|---|
| Liaison agent ID | `3f2a9c1e-...` (UUID) |
| Treasurer agent ID | `8b1d...` (UUID) |
| Model chosen for each | Claude Haiku |
| Whether the UI accepted the `input_schema` as given | yes / no + what it needed instead |
| Result of the check above | `completed` + the `setup-check:0` row exists |

Then set these on the backend's Vercel env (Harsha): `AGENT_RUNTIME=agenticorg`, `LIAISON_AGENT_ID`,
`TREASURER_AGENT_ID`, `AGENTICORG_BASE_URL=https://agenticorg.hackathon.pinelabs.com`, `AGENTICORG_API_KEY`.

## If something doesn't fit

- **The UI can't send a nested `args` object:** tell Divyansh. A flat-body adapter is a small change on our side.
- **The treasurer often times out:** the backend falls back to the same rules in code, so requests are still decided.
  Leaving the treasurer on the code path is also fine for the demo.
- **AgenticOrg is down during the demo:** set `AGENT_RUNTIME=local`. The same prompts and tools then run in our own
  backend, which needs `ANTHROPIC_API_KEY`.
