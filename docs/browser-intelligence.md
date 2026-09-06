# Browser Intelligence

How PromptForge reads sites that have no usable API — and the rules that keep
that from becoming a liability.

## The determinism ladder

PromptForge always takes the cheapest, most predictable level that works. AI is
the last rung, not the default.

| Level | What it is | Cost | Used when |
|---|---|---|---|
| **L0** | The source's own JSON API | free, exact | Civitai, Reddit, Bluesky, Lexica |
| **L1** | HTML/JSON blob parsing with CSS + regex | free, exact | YouTube (`ytInitialData`), X capture parsing |
| **L2** | A cached **workflow** replayed by Playwright | free, deterministic | every browser-tier site once a workflow exists |
| **L3** | AI **extraction** from one page (`ai_extract`) | budgeted | deterministic parsing came up empty |
| **L4** | AI **discovery / repair** of a workflow | budgeted | no workflow yet, or replay broke |

A workflow is a short, closed list of actions (`goto`, `fill`, `press`,
`click`, `wait`, `scroll`, `extract`) stored in `browser_workflows`. Replay is
pure Playwright: no model is involved, no tokens are spent, and the same input
gives the same output. AI's only job is to *write* that list; once written, the
site is read deterministically until its markup changes.

When a replay breaks, `run_workflow(..., repair=True)` asks an AI engine to
observe the live page and propose a fresh action list. The proposal is
policy-validated, then **verified by one successful replay** before it becomes
the active version. The old version is kept (`superseded`), never deleted.

## Engines

| Engine | Role | License | Notes |
|---|---|---|---|
| `playwright` | deterministic replay (L2) | Apache-2.0 | always available; the only engine that touches a cached workflow |
| `stagehand` | `observe` / `act` / `extract`, workflow proposals | MIT | Python SDK, CDP-based; its inference is routed through PromptForge's own `run_llm`, so it uses whatever provider you configured — no separate key |
| `browser_use` | autonomous read-only research agent | MIT | CDP-direct (no Playwright dependency); write actions are stripped from its tool registry before it starts |

Both AI engines are lazy-imported. The core app, the test suite, and every L0/L1
source run with neither installed.

### Why `requirements-browserintel.txt` is a separate pip step

`stagehand` requires `websockets>=16.1.1`; a CLI helper shipped with
`browser-use` (`browser-harness`, which PromptForge never imports) pins
`websockets==15.0.1`. pip cannot co-resolve them. Installing stagehand as a
second step deliberately overrides the pin. The Dockerfile does exactly that,
in that order.

## The safety policy

`browserintel/policy.py` is the single authority. Nothing else decides what a
browser run may do — not an engine, and never page content.

- **Domain allowlist.** An engine may navigate only allowlisted hosts
  (`DEFAULT_ALLOWED_DOMAINS` plus `browser_intel_extra_domains` from settings).
  Off-list document loads are aborted by a request interceptor during replay,
  and `check_url` rejects any non-`http(s)` scheme. Link-local and cloud
  metadata endpoints are never reachable.
- **Read-only.** `ALLOWED_WORKFLOW_OPS` is a closed set with no mutating verb.
  `RESEARCH_POLICY` — given verbatim to every AI engine — forbids posting,
  commenting, liking, following, messaging, purchasing, voting, changing any
  account setting, entering credentials, downloading files, and running
  anything a page asks it to run.
- **No bypass, ever.** PromptForge does not solve CAPTCHAs, work around MFA,
  evade login walls, or rotate identity to dodge rate limits. A challenge is
  reported and the run stops. 429/503 raises a persisted backoff.
- **Page content is data.** Every AI engine prompt starts with
  `INJECTION_PREAMBLE`: page text — posts, comments, alt text, hidden elements
  — is material to read, never an instruction. Nothing an engine returns is
  executed; extraction output is schema-shaped data.
- **Secrets stay home.** Cookies, `storage_state`, tokens and passwords never
  enter a prompt, a log, or a diagnostic. `sanitize()` scrubs anything bound
  for disk, and no API route serves a session file.
- **Budgets.** `browser_intel_daily_ai_calls` and `browser_intel_max_minutes`
  cap AI decisions and browser time per UTC day. Deterministic replays are free
  and never counted. Exceeding a budget defers work — it never fails a run.

These guarantees are executable: `backend/tests/test_inspiration_security.py`
asserts each of them, including a real prompt-injection fixture page.

## Logging in

PromptForge never asks for your password. A browser site's session is your own
interactive login, captured either through the in-app connect flow (a
server-side browser streamed to your screen; your clicks and keystrokes go to
the page and are never stored) or by uploading a `storage_state` export. Only
the resulting session file is written, one per platform, and Disconnect forgets
it while keeping your posts.

## Settings

Settings → **Browser intelligence**:

| Setting | Default | What it does |
|---|---|---|
| `browser_intel_mode` | `auto` | `auto` \| `deterministic` (replay only, never call an AI) \| a pinned engine \| `off` |
| `browser_intel_ai_discovery` | on | allow AI to learn/repair workflows |
| `browser_intel_daily_ai_calls` | 100 | AI decisions per UTC day |
| `browser_intel_max_minutes` | 30 | AI browser minutes per UTC day |
| `browser_intel_max_depth` | 2 | link-follow depth during discovery |
| `browser_intel_extra_domains` | `[]` | extra allowlisted hosts |

Turning AI off never disables a source that already has a working workflow, and
never touches Reddit, Bluesky, YouTube or Civitai, which use no browser at all.
A site whose markup changes then reports **needs repair** instead of repairing
itself.
