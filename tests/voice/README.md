# Voice test set

30 helper voice notes (12 Kannada, 12 Hindi, 6 mixed or noisy) and what the liaison agent must do with each.
`cases.jsonl` holds one case per line:

```json
{"id": "kn_01", "group": "kn", "audio": "tests/voice/kn_01.ogg", "lang": "kn",
 "say": "Somavara baralla, aidu nooru advance beku",
 "expect": [{"tool": "create_leave_request", "args": {"leave_from": "2026-10-26", "leave_to": "2026-10-26"}},
            {"tool": "create_advance_request", "args": {"amount_paise": 50000}}]}
```

- `group`: `kn`, `hi` or `mixed` (the 12/12/6 split); `lang`: the helper's language (`kn`, `hi`, `ta`, `te`, `en`),
  passed to the liaison and used as the speech-to-text hint, as the WhatsApp pipeline does.
- `say`: what the speaker says, romanised. It is the script for recording and the transcript in text-only runs.
- `expect`: the tool calls the agent must make, with only the arguments that matter (dates, `amount_paise`,
  `half_day`). `employment_id`, `note`, `item_note` and `source_message_id` are not checked. `"expect": []` means the
  agent must ask a clarify question and call no tool.
- `note` (optional): code-mix or background noise to reproduce when recording.
- Dates are written for **Saturday 2026-10-24**; the runner pins "today" to that date. "naale"/"kal" is 2026-10-25,
  "Somavara"/"Somvaar" is Monday 2026-10-26.

## Recording clips

- Record on a phone in WhatsApp (hold the mic, speak, send to yourself or the team group), then export the voice note.
  WhatsApp voice notes are already Ogg/Opus, which is what production receives. Any recorder that writes Ogg/Opus mono
  works too; `.opus`, `.mp3`, `.wav` and `.m4a` are accepted if you change the `audio` path.
- Name the file after the case id: `tests/voice/kn_01.ogg`, `tests/voice/hi_07.ogg`, `tests/voice/mx_03.ogg`.
- Say the `say` line naturally, as a cook or maid would to her employer: normal speed, fillers ("amma", "didi") are
  fine, small wording changes are fine as long as the meaning (day, amount, wallet vs own cash) stays the same.
- Mixed / noisy clips: follow the `note` (pressure cooker, mixie, traffic, Kannada-English mix). Keep each clip under
  20 seconds.
- Different speakers per language help; do not put real names, phone numbers or addresses in a clip.

## Running

From the repo root:

```bash
# Real speech-to-text for every clip that exists, real liaison model, fake tools
ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... python -m tests.voice.run

# No STT: each case's `say` text is the transcript (only ANTHROPIC_API_KEY needed)
ANTHROPIC_API_KEY=... python -m tests.voice.run --text-only

# One or a few cases
python -m tests.voice.run --text-only --only kn_01 --only hi_11      # or --only kn_01,hi_11
```

Keys come from the environment or the repo's `.env`. Missing keys stop the run with a one-line message (exit 2).
Cases whose clip has not been recorded yet run text-only automatically and are marked `text-only` in the table.

- Tools are faked: an `httpx.MockTransport` installed as `tools_client.http_factory` records every `POST /tools/{name}`
  and answers with `app/stubs.py` `TOOL_RESULTS`. Nothing reaches the backend and no money moves.
- The `agent_run` audit row is written when `DATABASE_URL` answers; otherwise (or with `--no-db`) it is skipped.
- `AGENT_RUNTIME=agenticorg` runs the liaison on AgenticOrg. AgenticOrg calls `/tools` itself, so the fake cannot
  intercept it: the runner refuses unless you pass `--allow-live-tools` (point AgenticOrg at a test backend first), and
  only tool names are compared because arguments are not visible.
- Other flags: `--cases PATH`, `--report PATH` (default `tests/voice/last_run.json`, which should stay out of git).

## What pass means

A case passes when the tools the agent called (calls that reached the tools endpoint) are the same multiset of tool
names as `expect`, and every expected argument equals the called argument (each expectation matched to its own call;
order does not matter; extra arguments are ignored). A clarify case (`expect: []`) passes when no tool was called and
the agent returned a clarify question. Calls the runtime rejected locally (bad arguments) are listed after `why:` when a
case fails.

The runner prints one row per case (id, language, mode, transcript, tools called, PASS/FAIL with the reason, STT ms,
liaison ms, total ms), then:

- pass count and rate (with the kn / hi / mixed split): **target at least 26 of 30** (scaled for `--only` runs);
- median, p90 and max total latency (STT + liaison): **target p90 under 10 s**. Download from WhatsApp, the treasurer
  and the reply send are not part of this number; production records them in `message.latency_ms`.

Exit code 0 when the pass target is met, 1 when not, 2 for configuration problems.
