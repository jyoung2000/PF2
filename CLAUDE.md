# PromptForge — project conventions (read me first, every session)

PromptForge is a self-hosted AI prompt intelligence, library & generation studio.
Docker container on port **5643**, Unraid-ready (amd64, CPU-only), data under `/data`.

## Session protocol
1. Read this file and `PROGRESS.md`.
2. `git log --oneline -15` to see where things stand.
3. Run the test suite (see Commands). Trust green tests + checked boxes; never re-plan or redo done work.
4. Resume from the first unchecked item in `PROGRESS.md`. Mark items done ONLY when their acceptance check passes; update `PROGRESS.md` immediately per item.
5. Commit small and often. Never leave the repo broken: when context runs low, finish the current piece, commit, add a "Next up:" note to `PROGRESS.md`, stop.

## Stack (exact)
- Backend: Python 3.12 (dev box has 3.11 + 3.12 — venv uses `/usr/bin/python3.12`), FastAPI, SQLAlchemy 2.x **sync** ORM + SQLite (WAL), APScheduler (BackgroundScheduler), httpx, crawl4ai+Playwright (Tier 2 only, lazy-imported), ffmpeg + Pillow.
- Frontend: React 18 + Vite + TypeScript + Tailwind CSS 3.4, built at image build time, served by FastAPI as static files. WebSocket for live scraper logs + generation progress.
- Integrations: Baserow via httpx; discord.py bot as background asyncio task in the same process.
- LLM client (knowledge/studio ONLY — never for scraping/parsing): Anthropic API, OpenAI-compatible, Ollama (direct URL or via desktop companion GPU bridge).
- Generation providers: fal.ai, Replicate, WaveSpeed AI — one adapter file each under `backend/promptforge/generation/`.

## Iron rules
- **Deterministic scraping — AI only for analysis.** Scrapers/parsers use JSON APIs, CSS selectors, regex. The LLM client is exclusively for the knowledge engine and Prompt Studio.
- Adapters fail independently; unconfigured ⇒ "Needs setup" in GUI, never an error.
- No captcha solving / challenge evasion. Interactive challenge ⇒ log + back off.
- All config via env / `.env` (defaults) overridden by GUI-editable `settings` table (live, no restart). Secrets write-only in UI (masked `••••1234`).
- Media: parse embedded metadata (PNG chunks/EXIF) BEFORE lossy compression. Images→WebP q82 max 2048px; videos→H.264 CRF27 max 1080p; thumbnails for both.
- Never hardcode credentials. Port 5643 everywhere.

## Directory layout
```
backend/
  requirements.txt          # pinned core deps
  requirements-browser.txt  # crawl4ai/playwright (Docker + Tier 2 dev only)
  requirements-dev.txt      # pytest, respx, ...
  promptforge/
    main.py        # app factory, static serving, lifespan (scheduler, discord, companion)
    config.py      # env config; DATA_DIR resolution (/data if writable else ./data)
    db.py models.py schemas.py settings_store.py aliases.py fts.py logbus.py scheduler.py
    api/           # one router file per area: posts, search, collections, tags, scrapers,
                   # settings, integrations, knowledge, studio, generation, companion, models_meta, ws
    pipeline/      # ingest.py (normalize→dedupe→download→metadata→compress→store→learn),
                   # media.py (download/compress/thumbs), metadata.py (PNG/EXIF parsing)
    scrapers/      # base.py (SourceAdapter, ScrapedPost), registry in __init__.py,
                   # civitai.py lexica.py browser_base.py midjourney.py tensorart.py seaart.py pixai.py
    knowledge/     # engine.py stats.py files.py techniques.py packs.py template_gen.py enhance.py
                   # foundation.md (shipped)
    llm/           # client.py (interface+factory), anthropic_client.py openai_client.py
                   # ollama_client.py companion_client.py
    generation/    # base.py fal.py replicate_provider.py wavespeed.py pricing.py router.py
    integrations/  # baserow.py discord_bot.py discord_rules.py
    companion/     # pairing.py manager.py (server-side WS hub + offline job queue)
  tests/           # pytest; fixtures under tests/fixtures/
frontend/          # Vite app (src/pages, src/components, src/api.ts, src/theme via Tailwind tokens)
companion/         # desktop tray app (Python): app.py, tray, ws client, ollama proxy; PyInstaller spec
scripts/capture_login.py
Dockerfile docker-compose.yml unraid-template.xml pricing.json .env.example
```

## Commands
- Dev setup (one command): `bash scripts/dev_setup.sh` (creates `backend/.venv` with python3.12, installs core+dev reqs, `npm ci` in frontend/)
- Backend dev server: `cd backend && .venv/bin/uvicorn promptforge.main:app --port 5643 --reload`
- Tests: `cd backend && .venv/bin/python -m pytest -q`  (browser deps NOT required)
- Frontend dev: `cd frontend && npm run dev` (proxies /api → :5643); build: `npm run build` (output `frontend/dist`, served by FastAPI when present)
- Container: `docker compose up --build` → http://localhost:5643 ; healthcheck `/api/health`
- Companion (from source): `python companion/app.py --server http://HOST:5643 --code XXXXXX`; `--headless` for no tray.

## Testing conventions
- Adapter parsers tested against saved fixture JSON/HTML in `backend/tests/fixtures/` — never live HTTP in tests. httpx mocked with `respx` (or transport MockTransport).
- LLM + generation providers + Baserow + Discord REST all mocked. `tests/conftest.py` provides tmp DATA_DIR + fresh DB per test.
- ffmpeg IS available in dev and image; compression tests use tiny generated media.

## Decisions
- D1: Dev venv uses python3.12 to match container image (`python:3.12-slim-bookworm`).
- D2: Sync SQLAlchemy + sync `def` FastAPI endpoints (threadpool). Async only for WebSockets, Discord bot, companion hub, generation queue worker.
- D3: FTS5 contentless tables (`posts_fts`, `saved_prompts_fts`) maintained by explicit code in `fts.py` (called from ingest/tag/collection/saved-prompt writes) — no SQL triggers, keeps it testable.
- D4: Masonry uses real media dimensions: `media_width`/`media_height` columns added to `posts` (captured during compression) → CSS grid row-span masonry (true left-to-right order).
- D5: crawl4ai + playwright isolated in `requirements-browser.txt`, lazily imported inside browser adapters, so the core app + tests run without them; Docker image installs them (`crawl4ai-setup` → Chromium).
- D6: Search qualifiers `tag:x model:y platform:z` parsed in `search.py`; free text → FTS MATCH (prefix `*` on last term for as-you-type); qualifiers → SQL filters w/ alias normalization for model.
- D7: Model alias map: seeded defaults in `aliases.py`, user rules in settings key `model_aliases` (JSON {pattern→canonical family}); normalization = lowercase, strip punctuation, then rule match, else first token heuristic.
- D8: Companion .exe cannot be cross-compiled from this Linux build env (PyInstaller limitation). Ship: companion source + `companion/build_companion.ps1` + PyInstaller spec + GH Actions workflow `build-companion.yml`; Settings serves a source zip download and points at the release exe. Marked experimental/deferred in PROGRESS/README.
- D9: Baserow database tokens can't always create tables (depends on instance/permissions): client tries `all-tables` listing + table create, and on 401/403 returns actionable guidance to paste an existing Table ID (field shown in the card). Contract encoded in mocked tests.
- D10: fal.ai test-connection = GET queue status for a nonexistent request id (401 ⇒ bad key; 404/422 ⇒ key OK) — never charges. Replicate = GET /v1/account. WaveSpeed = GET /api/v3/predictions/{fake}/result with same 401-vs-404 logic.
- D11: Knowledge files: markdown + YAML frontmatter under DATA_DIR/knowledge (`foundation.md` copied from package on first boot; `models/{family}.md`; `styles/collection-{id}.md`), hard cap 16KB enforced on write (sections trimmed oldest-exemplar-first). Deterministic stats live in `DATA_DIR/knowledge/stats/{family}.json` and are re-rendered into the md on update.
- D12: LLM analysis budget = settings `llm_daily_budget` (calls/day, default 200) + persisted counter keyed by UTC date; ignored when provider is ollama/companion (free/local).
- D13: Technique tags: deterministic keyword pass on every video ingest (free) + LLM batch refinement when budget allows. Taxonomy fixed in `knowledge/techniques.py`.
- D14: Generation flow is async in-process queue (`generation/queue` in router.py): estimate → create `generations` row → worker calls provider adapter → poll → download output → ingest pipeline (`origin=generated`) → learning event. Progress via WS `/api/ws/generation`.
- D15: Discord bot runs only when token present; started/stopped from settings changes via `integrations/discord_bot.py` manager. Channel listing/test via Discord REST (httpx), bot gateway via discord.py.
- D16: `pricing.json` seeded at repo root, copied to DATA_DIR on first boot (GUI-editable copy wins).
- D17: Frontend fonts self-hosted via @fontsource (Space Grotesk display, Inter body) — offline-friendly.
- D18: Dedupe key `(platform, platform_post_id)` UNIQUE; re-scrape updates mutable fields (favorite/tags/collections preserved).
- D19: Media on disk: `DATA_DIR/media/{platform}/{post_uuid}.{ext}`, thumbs `DATA_DIR/media/{platform}/thumbs/{post_uuid}.webp`; served at `/media/*` by FastAPI StaticFiles.
- D20: Tests use `TestClient` (starlette) — covers WS endpoints too. pytest-asyncio only where an event loop is unavoidable (companion manager unit tests).
- D21: Lexica API can be flaky/down: adapter marks itself "experimental-degraded" health on repeated 5xx but stays enabled; errors never raise out of `run_scraper`.
- D22: All scraper runs execute in a single worker thread (`scheduler.py` global lock) — one site at a time, Chromium only during browser runs.
- D23: Settings GET masks secret keys (list in `settings_store.SECRET_KEYS`) as `••••` + last4; PUT with value `"__unchanged__"` keeps stored secret.
- D24: Videos: `technique_tags` JSON column on posts (list[str]); images may also get technique tags from LLM pass but facet UI targets videos primarily.
- D25: Companion WS protocol (JSON): client→ `{t:"hello", name, ollama_models:[...]}`, `{t:"pong"}`, `{t:"result", id, ok, data|error}`, `{t:"chunk", id, data}`; server→ `{t:"ping"}`, `{t:"request", id, method:"ollama.generate"|"ollama.chat"|"ollama.tags", payload}`. Auth: `?token=` query param checked against sha256 of stored pairing tokens.
- D26: In tests and dev without real keys, LLM factory returns `MockLLM` when settings `llm_provider="mock"` — deterministic canned outputs; never selectable in UI (tests/dev only).
- D27: Civitai adapter maps meta keys: prompt, negativePrompt, seed, steps, sampler, cfgScale, Size, Model + resources/civitaiResources when present; items with null meta skipped unless settings `civitai_keep_metaless=true` (then media-only).
- D28: Cursor pagination everywhere: `/api/posts` & search return `{items, next_cursor}` with cursor = last post id (descending id order).
- D29: Generation "recommended model" = template.recommended_model or collection model_family; provider auto-pick = min cost among **connected** providers offering that family (pricing.py); override allowed, UI shows gentle note when off-recommendation.
- D30: Companion job queue = DB table `llm_jobs` (kind, payload JSON, status queued|running|done|error, result) drained by scheduler when companion online or when cloud fallback enabled+configured.
- D31: Baserow media upload uses the **compressed** local file via user-files upload endpoint; sync tracks `synced_to_baserow`, never double-pushes (skip already-synced unless "force").
- D32: Discord rules stored in settings `discord_rules` (JSON, see integrations/discord_rules.py DEFAULT_RULES); evaluation is pure function `select_posts(rules, posts)` — unit-tested for every mode/filter/routing/digest/throttle combo.
- D33: `.pfpack` = zip with `manifest.json` {kind, family/collection, exported_at, versions} + `model.md`/`style.md` + `template.json` + `template.txt` + optional `exemplars/*.webp`; import merges newer-wins per file mtime in manifest, logged to `DATA_DIR/knowledge/import.log`.
- D34: Frontend state: no heavy state lib; small `useApi` hooks + module-level caches; react-router v6; toasts via tiny custom store.
- D35: Scheduler default intervals: civitai 10m, lexica 15m, browser sites 60m (min civitai 5m enforced); learning pass hourly; digest per rules; all editable in GUI.
- D36: `posts.params` JSON also holds `_original_bytes`/`_stored_bytes` per post for storage-savings stats.
- D37: Replicate adapter file named `replicate_provider.py` to avoid shadowing the (unused) `replicate` pip package name.
- D38: Version endpoint `/api/health` returns {status:"ok", version, db:"ok", data_dir, ffmpeg:bool}; docker HEALTHCHECK curls it.
- D39: Model catalog page = `/api/models/meta` aggregation (family, versions seen, counts, first/last seen, is_new<14d) — purely data-driven from posts.
- D40: NSFW default filter = hide NSFW in gallery unless toggled; per-request override param; setting `nsfw_default_show` (bool, default false).
- D41: Studio Enhance without configured LLM returns 409 `llm_not_configured` with guidance; UI shows setup pointer instead of error toast.
- D42: Companion pairing codes: 6 digits, TTL 10 min, single-use, issued from Settings; token = `pfc_` + 32 hex; server stores sha256(token) in `companions` table with name + last_seen; revoke deletes row and closes WS.
- D43: WS auth for scraper logs/generation progress: same-origin only, no token (read-only logs); companion WS requires token (D25).
- D44: Time in DB = UTC ISO strings via SQLAlchemy DateTime(timezone=True); `TZ` env honored for APScheduler display only.
- D45: Deleting a post removes DB row + media files; collection covers fall back to next newest member.

- D46: The remote build environment's egress proxy blocks all art-site hosts (403 CONNECT even to civitai.com — verified via `$HTTPS_PROXY/__agentproxy/status`, policy denial). Consequences: (a) Tier 2 adapters are built against fixture JSON encoding the sites' known internal API shapes with deliberately defensive multi-shape parsers; (b) the Phase 10 "live Civitai smoke test" runs the full Docker stack against a local Civitai API stand-in (same wire format), and true live verification is a documented first-boot step for the user's own network (their Unraid has open egress). Never "fix" scrape failures in this sandbox by weakening adapters — the code targets the real sites.
- D47: Tier-2 media downloads reuse the login session: BrowserAdapter.make_client() loads cookies out of the site's Playwright storage_state JSON into the httpx client jar.
- D48: crawl4ai runner bridge: sync `fetch_recent` → `asyncio.run()` of one `arun()` per run inside the scheduler's worker thread; response bodies captured via `on_page_context_created` hook attaching `page.on("response")` (capture_network_requests alone doesn't keep bodies). 429/503 → exponential backoff persisted in ScraperState.state["backoff_until"].

- D49: Offline-LLM job drain (companion): LlmJob rows are queue markers; drain re-runs the idempotent watermark-based learning pass (analyze_family) rather than replaying raw stored prompts, then marks jobs done — same visible behavior (queue count in GUI, drain on reconnect), no lost context.
- D50: Sandbox docker verification (Phase 10): Docker Hub CDN blocked → dockerd runs with --registry-mirror=https://mirror.gcr.io; the shipped Dockerfile (python:3.12-slim + crawl4ai-setup) cannot build here (deb.debian.org + Playwright CDN blocked), so the container E2E ran on a sandbox-only ubuntu:24.04 variant (scratchpad/sandbox.Dockerfile — same layout/entrypoint/healthcheck/CMD, no browser stack). Full smoke passed: healthcheck healthy, E2E Civitai-wire-format scrape (7 posts incl. video), compression+thumbs+embedded-metadata, knowledge files, template assembly, PUID/PGID ownership, empty-env + network-kill failure paths. The real Dockerfile is standard and is expected to build anywhere with normal egress — first user boot should run a live Civitai scrape as final confirmation.

- D51: X feature: one Post per media item — platform_post_id = tweet id for the first media, `{tweet_id}-{n}` for extra photos in a multi-image tweet; dedupe therefore stays per tweet+media. Freeform text parsing lives in `scrapers/x_text.py` (deterministic; confidence high|low in params.prompt_confidence, model_stated bool). Low-confidence text is EXCLUDED from knowledge stats/analysis (post still counted in media tallies).
- D52: Monitored-account validation is format-only at add time (regex on normalized handle); real resolution happens on first poll — an account that 404s flips to status "not found" on its row. Adds never block on the browser.
- D53: Grok = xAI's OpenAI-compatible API (base https://api.x.ai/v1). Two layers: (a) `integrations/grok.py` — raw chat with optional live-X `search_parameters`, own budget/usage counters (settings grok_*), all X-specific discover/curate/digest logic; (b) LLM factory gains provider "grok" (reuses OpenAIClient with the xAI base) so the knowledge engine can use Grok too. Every Grok feature no-ops with a "Needs setup" state when no key.
- D54: Grok curation writes: params.grok = {checked_at, ai_media: bool, model_confidence: stated|inferred}; inferred model fills model_name/model_family ONLY when empty; technique suggestions whitelisted against the taxonomy; tag suggestions become ordinary user tags (reviewable/removable). Non-AI-flagged posts are kept, never auto-deleted.
- D55: XAdapter start_url is set per run (search crawl rotates settings terms like Lexica; account polls crawl x.com/{handle}/media first, falling back to the profile) — BrowserAdapter instance state is safe because the scheduler serializes all browser runs (D22).

- D56: One-click in-app login (`scrapers/connect.py` + `/api/ws/connect/{platform}`): server-side headless Chromium streamed as JPEG frames over a same-origin WS (origin checked explicitly — absent Origin allowed for non-browser clients, mismatch → close 4403); client forwards click/text/key/scroll/paste; the HUMAN performs the entire login (this is capture_login.py with the display moved into the browser — never login automation, never captcha/challenge evasion). Auto-save when X's `auth_token` cookie appears (checked only on idle ticks so input bursts fully land first); other sites use the modal's manual "Save session now". One session per platform, 5-min idle + 15-min hard timeout, browser always closed with the socket, keystrokes never logged/stored — only storage_state is written (and the sticky session_expired flag cleared). Playwright lazy-imported (D5); `PF_LOGIN_URL_<SITE>` and `PF_CHROMIUM_PATH` env overrides exist for stand-in smoke tests (precedent D46/D50) and odd hosts.
- D57: Session REST: `POST /api/scrapers/{name}/session` (multipart upload of a storage_state export; validates JSON shape + 2MB cap; clears expired flag) and `DELETE .../session` (disconnect — removes the file, keeps posts). Both 404 for non-browser adapters.
- D58: Grok quick-connect: pasting/committing a key in the Grok card auto-saves then auto-runs the connection test (badge + live model list with no further clicks); "Get an API key ↗" links console.x.ai. Secret handling unchanged (D23 masking, `__unchanged__`).

- D59: Connect-everywhere model: every adapter declares `auth_kind` (session | api_key | none; api_key adapters also `api_key_setting` + `api_key_url`), and `/api/scrapers` reports `session_status` for EVERY browser adapter (optional logins flagged `session_optional`), `connectable` (has a LOGIN_URL), `key_configured`/`key_setting`/`key_url`. Login detection in `connect.py`: `KNOWN_LOGIN_MARKERS` (cookie-name substrings — x `auth_token`, midjourney `Midjourney.AuthUserToken`) → final save + close; every other site → generic detection: baseline of cookie names + localStorage keys taken at the user's FIRST input, then on idle ticks any NEW name matching `AUTH_NAME_RE` (auth|token|session|jwt|login|sid|uid|access|refresh|passport) and not `NOT_AUTH_RE` (csrf|xsrf|_ga|analytics|consent|cf_…) → NON-final save (`{t:"saved", final:false}`), window stays open ("Done" closes, "Save session now" re-saves). Never fires on what the page set on load; a false positive only means an early save the user re-saves over.
- D60: `POST /api/scrapers/{name}/test` → `adapter.test_connection(s)` returning `{ok, detail}` (never raises, always HTTP 200; 404 when the adapter has no test). Civitai = one `?limit=1` request with the bearer key: 200 ⇒ ok, 401/403 ⇒ bad key, other ⇒ transient, network error ⇒ "Can't reach"; `make_client(s, transport=None)` exists for injection. Frontend `ApiKeyConnect`: paste/Enter/blur → save → auto-test; "Remove key" saves ''.

- D61: Schema migrations are additive and automatic: `db.migrate_schema()` runs after `create_all` on every boot — for each existing table, any column the model declares but the table lacks is added via `ALTER TABLE ADD COLUMN` with the model default (JSON dict/list defaults become `'{}'`/`'[]'` literals), and missing indexes are created. Never drops/renames/rewrites rows. Tested against a v1.0-shaped `posts` table.
- D62: Layered post envelope lives ON `posts` (no parallel tables): `observed` (NormalizedPost — identity/author/engagement/text/media/relations, exactly what the source showed), `enrichment` (detail/author/comments lookups), `analysis` (AI verdicts + score breakdowns), `assertions` (provenance per field) + indexed scalars (`candidate_score`, `inspiration_score`, `ai_status`/`ai_confidence`, `content_hash`, `phash`, `engagement_total`, `creator_id`, `has_workflow`, `prompt_source`, `model_source`, `pipeline_state`, `discovered_at`). Adapters pass `ScrapedPost.observed`; legacy `params.engagement/hashtags` are folded in for backward compatibility. `engagement_snapshots` append per ingest; `creators` upserted per (platform, handle).
- D63: Central staged queue = `pipeline_jobs` (stage enrich|analysis|knowledge; state queued|processing|complete|skipped|failed|retryable; priority/attempts/cost) drained by the scheduler every minute (`intel/queue.tick`). Stage handlers register at import; raising `Deferred` (budget/offline) leaves the job queued with no attempt counted and stops the tick for that stage; other exceptions → retryable (10-min backoff) until `max_attempts` → failed. Discovery→dedupe→score→download→metadata stay synchronous inside ingest (cheap); only enrich/analysis/knowledge go through the queue.
- D64: Scores are deterministic weighted averages (0–100) with breakdowns stored in `analysis`; weights overridable via settings `intel_weights` {candidate:{…}, inspiration:{…}}. Candidate Score gates BEFORE download (`intel_min_candidate_score`, default 25; `ingest_batch(gate=False)` for monitoring/generation paths); `intel_enrich_threshold` (candidate ≥ 60) enqueues ENRICH, `intel_analysis_threshold` (inspiration ≥ 70) enqueues ANALYSIS.
- D65: Dedupe levels: platform id UNIQUE (existing) → sha256 of the ORIGINAL bytes (`content_hash`) → 64-bit dHash (`phash`, hex; Pillow-only, no numpy) with hamming ≤ `intel_near_dup_distance` (6) → symmetric rows in `post_links` (kind exact|near|repost|similar|related). Links never delete; near-dup count feeds the novelty component.
- D66: Provenance: `assertions[field] = {value, source, confidence, evidence}` with source rank user > observed = metadata > extracted > inferred > ai; a lower-ranked writer never replaces the canonical value (it is kept under `_alternates`). Canonical columns (prompt/model) are read from assertions; `model_source` collapses to explicit|metadata|inferred|ai for search/UI.

- D67: Metadata extraction (`pipeline/metadata.py`) merges every embedded format found in priority order A1111/Fooocus → ComfyUI (API graph, or UI graph normalised via known `widgets_values` layouts + links) → NovelAI → InvokeAI → SwarmUI → EXIF UserComment/ImageDescription → XMP (dc:description, CreatorTool, IPTC trainedAlgorithmicMedia flag) → video container tags via ffprobe + sidecar .json/.txt. Parsers are pure; `_tag()` labels `metadata_format(s)` and stores every recognised chunk AND every unknown text chunk under `params._raw_metadata` (64KB cap per value) — unknown metadata is never discarded. Canonical params: seed/steps/cfg_scale/sampler/scheduler/model/vae/size/denoise/clip_skip + `loras[]`, `controlnet[]`, `hires{}`, `upscale{}`, `video{model,frames,fps,duration_s,mode}`, `references[]`, `extra{}`.

- D68: Extraction (`intel/extract.py`) is deterministic and evidence-tagged: model versions per family (`MODEL_VERSION_RES`), camera vocabulary (lens mm, shot size, angle), lighting, composition and the expanded technique taxonomy all land in `assertions` with source `extracted` + a quoted evidence snippet; `classify_heuristic` sets a 5-level `ai_status` (AI-native platforms / embedded metadata ⇒ definitely_ai; real-camera claims ⇒ probably_not_ai; named model or AI hashtags ⇒ probably_ai; else uncertain) that a later LLM verdict may replace but the heuristic never re-overwrites. Runs on every ingest inside `_post_store_intel`.
- D69: The ONLY LLM contact for scraped posts is `intel/analysis.py` (queue stage `analysis`, gated by `intel_ai_analysis_enabled`, the central `run_llm` budget — BudgetExceeded ⇒ `Deferred`, no provider ⇒ `skipped`). It asks for ai_status/confidence/reason, a prompt ONLY when none is high-confidence, a model ONLY when none is explicit (written as source `ai`, `model_source="ai"`, `params.model_inferred`), whitelisted technique slugs and descriptors; provenance ranking makes AI output an `_alternates` entry whenever explicit data exists. Knowledge stats accept prompts only when `is_high_confidence(assertions, "prompt", knowledge_min_confidence)` and skip inferred/AI models unless `knowledge_accept_ai`; stats now track prompt structure, aspect ratios, techniques, engagement-weighted terms, creators, references and weekly counts.

- D70: Every adapter declares `capabilities` (search detail author comments thread video metadata browser_session api related) and optional lookups `fetch_comments/fetch_thread/fetch_related/fetch_author(s, client, id)`; nothing undeclared is ever attempted or shown. Civitai: related = siblings via `postId` (stored as `params._civitai_post_id`), author = `/api/v1/creators?query=`; X: one TweetDetail capture per post serves both `comments` (others) and `thread` (the author's own replies), parsed deterministically by `parse_detail`. The enrichment stage (`intel/enrichment.py`, queue stage `enrich`) runs only for candidates above `intel_enrich_threshold`, takes the scheduler lock for browser adapters, stores everything under `post.enrichment` as observed data, and turns a labelled "Prompt:"/model in the AUTHOR's reply into `extracted` assertions (never overriding explicit ones); comments are ranked author → technical (model/prompt/workflow/seed/LoRA/… terms) → engagement, capped at 25. Run metrics live in `ScraperState.state.runs` (rolling 20) and `intel/sources.py` derives yields, duplicate rate, reliability and an ADVISORY priority recommendation (`GET /api/scrapers/{name}/metrics`); nothing is auto-disabled. Snapshots (`intel_snapshots`, off by default) gzip sanitized captures under DATA_DIR/snapshots/{platform} (credential-looking keys dropped, bearer-like values redacted, 50 per platform).

- D71: Creator intelligence (`intel/creators.py`) is computed deterministically from stored posts per `creators` row (cadence, avg/median engagement, AI ratio, prompt availability, models/techniques/styles, top+recent posts, weekly engagement trajectory + trend, metadata richness) into `creators.stats`, refreshed lazily when older than 1h or on `POST /api/inspiration/creators/{id}/refresh`; monitored accounts surface their creator summary. Grok discovery is an EVIDENCE model: candidates carry `source:"grok", verified:false` plus evidence/detected_models/content_type/engagement_estimate/confidence; "Watch" stores that claim in `monitored_accounts.evidence` (only when `added_by="grok"`), and the first successful poll that sees real posts flips `verified` — LLM-claimed models never touch posts/creators. Followed accounts skip the Candidate Score gate (`ingest_batch(gate=False)`). Grok Web = a grok.com browser session captured with the standard connect flow (platform "grok", marker cookie `sso`), reported by `GET /api/grok/status.web_session` and removable via `DELETE /api/grok/session`; it is explicitly NOT an API credential and no feature requires it yet. Settings groups all three under "Social accounts" with a feature→credential map.

- D72: Advanced search lives in `intel/query.py` (deterministic parser → `ParsedQuery`; unknown values are reported in `ignored`, never fatal) and is applied inside the existing `/api/search` (which `/api/inspiration/search` wraps): `has:` (prompt|workflow|video|image|metadata|comments), `creator:`, `technique:`, `camera:` (assertions/prompt LIKE), `after:`/`before:` on `coalesce(posted_at, scraped_at)`, `engagement:`/`inspiration:` with `> >= < <= =`, `ai:true|false|uncertain` (5-level status buckets), `model_source:`, `sort:` (inspiration|engagement|newest|oldest; sorted listings use an offset cursor, FTS results are re-ranked in memory). Clusters are rule-based (`intel/clusters.py`: topic/model/technique/style/palette/subject/creator/media/prompt-structure/camera/engagement-viral) materialised into `clusters` + `cluster_posts` (score = Inspiration Score, ≥2 members, stable ids across rebuilds, every 30 min + `POST /clusters/rebuild`); inferred/AI models never form model clusters. Similarity (`intel/similar.py`) = dHash hamming (visual), phrase-set Jaccard over FTS candidates (prompt), technique overlap, and best-for-model (high-confidence prompts only) — no vector DB. Trends (`intel/trends.py`) = weekly series per kind with a `rising` list (last 2 weeks vs prior, ≥3 recent, ratio ≥1.5); the optional LLM summary receives ONLY that JSON and is stored in settings `intel_trend_summary` with what it was grounded in.

- D73: Inspiration UI: top nav = Gallery · Collections · Models · Inspiration · Studio · Settings; `/inspiration/*` hosts Overview, Sources (the former Scrapers page), Creators (the former Monitoring page + creator intelligence), Clusters, Queue, Analytics, plus `creators/:id` and `clusters/:id`; the legacy `/scrapers` and `/monitoring` routes redirect. Post intel renders in `IntelPanel` inside the existing DetailDrawer (which now owns a `currentId` so Find-similar/related navigate in place). "Use as Inspiration" hands off through localStorage key `pf.inspiration.context` (`lib/inspiration.ts` builds/loads/clears it) and opens Studio Enhance with `?inspiration=1`; the Studio panel offers Insert structure / Use source prompt / attribution — the context is never sent to the server by itself, only what the user inserts into the prompt.

*(append new decisions here as D74, D75, …)*
