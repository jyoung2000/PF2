# PromptForge build progress — single source of truth

Rules: work top to bottom; check a box ONLY when its acceptance check passes; update immediately;
commit per sub-task or logical unit; end each phase with its gate (full test suite + phase verify + commit `phase-N complete`).

## Phase 1 — scaffold, data model, pipeline, Tier 1 adapters, minimal API
- [x] 1.1 Repo scaffold: .gitignore, .env.example, scripts/dev_setup.sh, backend venv (py3.12), pinned requirements{,-dev}.txt install clean. ✓: `dev_setup.sh` exits 0; `python -c "import fastapi"` works.
- [x] 1.2 config.py (env + DATA_DIR resolution) + db.py (WAL SQLite engine/session) + logbus.py. ✓: unit test creates tmp DB, WAL mode on.
- [x] 1.3 models.py: all tables from spec (posts, tags, post_tags, collections, collection_posts, reference_images, ref_links, saved_prompts, templates, generations, settings, companions, llm_jobs) + create_all + FTS5 DDL in fts.py. ✓: test creates schema, inserts + FTS round-trip.
- [x] 1.4 settings_store.py: DB>env>default merge, secret masking, live updates. ✓: unit tests.
- [x] 1.5 aliases.py: normalization + seeded defaults + user rules. ✓: unit tests (flux variants → "flux").
- [x] 1.6 pipeline/metadata.py: PNG text-chunk (A1111 params, ComfyUI workflow) + EXIF parse. ✓: fixture PNGs parse.
- [x] 1.7 pipeline/media.py: download (same-session client), compress image→WebP(q82,max2048), video→H264 CRF27 max1080p, thumbs (ffmpeg frame-grab for video), byte stats. ✓: tests with generated media; output smaller+valid; metadata extracted BEFORE compression.
- [x] 1.8 scrapers/base.py (SourceAdapter, ScrapedPost, registry) + pipeline/ingest.py (normalize→dedupe→download→meta→compress→store→learn hook→autopush hook). ✓: ingest test with fake adapter: dedupe works, files land in DATA_DIR.
- [x] 1.9 Civitai adapter (cursor pagination, meta mapping D27, video detection, ≥5m poll). ✓: parser tests on fixture JSON incl. video item + null meta.
- [x] 1.10 Lexica adapter (search terms from settings, graceful-down D21). ✓: parser tests on fixture JSON.
- [x] 1.11 Minimal API: /api/health, /api/posts (cursor, filters), /api/posts/{id} (detail incl. media URLs), /api/scrapers + run-now (sync run in thread), /media static. ✓: TestClient tests green.
- [x] 1.12 Phase gate: full pytest green; commit `phase-1 complete`.

## Phase 2 — frontend gallery + detail + search
- [x] 2.1 Vite+React+TS+Tailwind scaffold with design tokens (colors #0E0F12 base, accent, spacing, radius), fonts (@fontsource Inter + Space Grotesk), dark-first. ✓: `npm run build` clean.
- [x] 2.2 App shell: header (wordmark, nav, integration status dots), responsive, focus states, reduced-motion. ✓: renders at 375px & desktop.
- [x] 2.3 api.ts typed client + useApi hooks + toast store + Skeleton/EmptyState components. ✓: tsc clean.
- [x] 2.4 Masonry gallery (grid row-span via media dims), blur-up thumbs, video hover-preview + duration badge, infinite scroll. ✓: manual check vs seeded data.
- [x] 2.5 Search bar (debounced FTS + `tag:`/`model:` qualifiers + type-ahead for models/tags) + filter bar (platform, model, media, technique, NSFW, favorites, date). ✓: API search tests + UI check.
- [x] 2.6 Backend /api/search (FTS + qualifiers + filters + collection scope) + /api/suggest. ✓: pytest incl. qualifiers.
- [x] 2.7 Detail drawer: media viewer, prompt + copy, negative, param chips, tag editor w/ autocomplete, source/author, actions (favorite, save-to-collection, baserow, discord, delete) — actions stubbed where later. ✓: favorite/delete/tag flows work end-to-end in UI.
- [x] 2.8 FastAPI serves built frontend (SPA fallback). ✓: `curl /` returns app HTML after build.
- [x] 2.9 Phase gate: pytest + npm build + manual smoke; commit `phase-2 complete`.

## Phase 3 — collections, tags, scrapers dashboard, scheduler, settings, WS logs
- [x] 3.1 Collections API: CRUD, save/remove post, model-family scoping (block cross-family w/ clear error unless allow_mixed), covers, counts. ✓: pytest incl. scoping cases.
- [x] 3.2 Model collections (automatic, from alias map) + /api/models/meta (counts, first/last seen, New badge). ✓: pytest.
- [x] 3.3 Collections UI: index (model + user sections, mosaic covers), collection page = full gallery experience (scoped search, image/video filter, prompt-caption hover, remove-from-collection). ✓: manual smoke.
- [x] 3.4 Save-to-collection popover (matching-family first, inline new collection, mixed-model message). ✓: manual + API tests.
- [x] 3.5 Tags API (add/remove, autocomplete) wired into FTS. ✓: pytest.
- [x] 3.6 APScheduler: per-adapter interval jobs, one-at-a-time lock, run-now, next-run times. ✓: pytest (fake clock/short interval).
- [x] 3.7 WS /api/ws/logs live scraper tail via logbus. ✓: TestClient WS test.
- [x] 3.8 Scrapers dashboard UI: adapter cards (status/last run/items/next run/toggle/interval/run-now) + live log tail. ✓: manual smoke.
- [x] 3.9 Settings backend: GET/PUT with masking, storage stats endpoint, purge tool. ✓: pytest.
- [x] 3.10 Settings UI: scraper keys (Civitai, Lexica terms), NSFW default, compression quality, storage stats + purge. ✓: manual smoke.
- [x] 3.11 Phase gate; commit `phase-3 complete`.

## Phase 4 — Baserow + Discord (guided setup + test flows)
- [x] 4.1 Baserow client: token check, list tables, find/create PromptForge table + fields, row push w/ file upload (compressed), sync tracking. ✓: mocked-httpx tests incl. each error mode (401 token, no-perm, network).
- [x] 4.2 POST /api/integrations/baserow/test full E2E check + specific errors; auto-sync toggle honored by pipeline. ✓: pytest.
- [x] 4.3 Discord REST helpers: token validate, guilds/channels list, send test embed (delete after 10s), invite URL from client id. ✓: mocked tests each failure mode.
- [x] 4.4 discord.py bot manager: start/stop on settings change, embeds, slash commands /latest /random /search, auto-post w/ throttle. ✓: unit tests on command handlers w/ mocked interactions; bot object not connected in tests.
- [x] 4.5 POST /api/integrations/discord/test + status endpoints. ✓: pytest.
- [x] 4.6 Settings UI: Baserow + Discord guided setup cards (steppers, live status badges, test buttons, last-tested, header indicators). ✓: manual smoke vs mocked backend errors.
- [x] 4.7 Per-post actions Send to Baserow / Post to Discord wired (toasts on error). ✓: pytest + manual.
- [x] 4.8 Phase gate; commit `phase-4 complete`.

## Phase 5 — Tier 2 browser adapters
- [x] 5.1 browser_base.py: crawl4ai runner (stealth, rate limiter, network capture, storage_state, one-at-a-time), lazy imports, session status (valid/expired/missing). ✓: unit tests with crawl4ai mocked.
- [x] 5.2 scripts/capture_login.py (headed login → storage_state export). ✓: script runs `--help`; manual-use documented.
- [x] 5.3 Midjourney adapter (VirtualScroll, intercept JSON, requires session). ✓: parser tests on fixture JSON.
- [x] 5.4 TensorArt adapter (network capture JSON). ✓: parser tests on fixture JSON.
- [x] 5.5 SeaArt adapter. ✓: parser fixture tests.
- [x] 5.6 PixAI adapter. ✓: parser fixture tests.
- [x] 5.7 GUI: session status per site, experimental badges, graceful degradation. ✓: manual smoke w/o sessions.
- [x] 5.8 Phase gate; commit `phase-5 complete`.

## Phase 6 — knowledge engine
- [x] 6.1 Write foundation.md (prompt anatomy, shots/angles/movement, composition, lighting, color, styles, motion/pacing, audio cues, consistency incl. seeds/srefs/LoRAs, negative prompting, cinematic heuristics). ✓: file ships, <16KB, copied to DATA_DIR on boot.
- [x] 6.2 llm/client.py interface + factory + MockLLM + anthropic/openai/ollama clients + budget guard (D12) + usage counter. ✓: mocked tests; budget respected.
- [x] 6.3 stats.py deterministic layer: term/descriptor freq, length dist, param histograms per family, updated on every ingest. ✓: pytest exact numbers.
- [x] 6.4 files.py: knowledge md read/write, YAML frontmatter, 16KB cap, section merge; models/{family}.md auto-created on first sighting. ✓: pytest (create-on-first-sight, update-in-place, cap enforced).
- [x] 6.5 engine.py: scheduled learning pass (batch ≤50/family), generation-event learning, prompt-cluster distillation into workflow notes. ✓: mocked-LLM tests.
- [x] 6.6 techniques.py taxonomy + deterministic keyword pass + LLM refinement; technique facet in search API. ✓: pytest.
- [x] 6.7 styles/{collection}.md profiles built/refreshed on demand + on collection change. ✓: mocked tests.
- [x] 6.8 Knowledge packs .pfpack export/import (merge newer-wins, logged). ✓: round-trip test identical.
- [x] 6.9 Knowledge API + Settings UI (LLM provider picker + test, budget, usage counter) + models page knowledge view. ✓: pytest + manual.
- [x] 6.10 Phase gate; commit `phase-6 complete`.

## Phase 7 — Prompt Studio
- [x] 7.1 template_gen.py: style profile → template (schema_json slots from learned vocab, text_template, ref_slots, recommended_model); refresh on profile update. ✓: mocked tests.
- [x] 7.2 Templates API CRUD + render/assemble endpoint (slots→prompt). ✓: pytest round-trip schema→form→prompt.
- [x] 7.3 Template export/import JSON + written-text format. ✓: round-trip identical test.
- [x] 7.4 Studio UI: Templates tab (cards by collection, visual form from schema_json, ref-image slots w/ drag-drop, live preview, Copy/Save/Generate). ✓: manual smoke.
- [x] 7.5 Enhance: backend (foundation+model+style context, before/after + why-notes) + UI tab w/ diff highlights; 409 when no LLM (D41). ✓: mocked tests + manual.
- [x] 7.6 Saved prompts: API (save/star/search across saved+scraped, filters) + UI tab. ✓: pytest.
- [x] 7.7 reference_images: upload/dedupe(sha256)/roles, linked to saved prompts + generations. ✓: pytest.
- [x] 7.8 Template editor UI (slots/options/defaults/skeleton/refs/model). ✓: manual smoke.
- [x] 7.9 Phase gate; commit `phase-7 complete`.

## Phase 8 — Generation hub
- [x] 8.1 generation/base.py + fal.py + replicate_provider.py + wavespeed.py (submit/poll/download; test_connection D10). ✓: mocked tests per provider incl. error modes.
- [x] 8.2 pricing.py: pricing.json seed (image per-image, video per-second×res), DATA_DIR copy, GUI-editable API. ✓: estimate math tests image+video.
- [x] 8.3 router.py: cheapest-connected-provider auto-route + override + per-model price list for dropdown. ✓: routing tests.
- [x] 8.4 Generate API: estimate → queue → worker → provider → download → ingest(origin=generated, links) → learn; WS progress; spend totals per provider; no double-charge on error. ✓: mocked E2E test.
- [x] 8.5 Settings UI: AI Providers cards (fal/replicate/wavespeed) guided setup + test; spend totals. ✓: manual smoke.
- [x] 8.6 Generate UI: from Studio + "Recreate" in drawer; recommended model preselected; price-per-model dropdown; off-recommendation note; queue progress. ✓: manual smoke (mock provider in dev).
- [x] 8.7 Phase gate; commit `phase-8 complete`.

## Phase 9 — companion app + Unraid packaging + Discord rules panel
- [x] 9.1 companion server side: pairing (code issue/verify TTL/single-use, token sha256, list/revoke), WS hub (auth, hello/models, request/response, heartbeat), llm_jobs queue + drain on reconnect + cloud fallback toggle. ✓: pytest incl. bad-token reject, queue+drain.
- [x] 9.2 llm/companion_client.py implements LLM interface via hub. ✓: mocked-hub test.
- [x] 9.3 companion desktop app: ws client, ollama proxy (tags/generate/chat ONLY), tray UX (pystray; --headless), start-with-Windows toggle, mini log, reconnect w/ backoff. ✓: pytest against mocked ollama + real server TestClient/live WS.
- [x] 9.4 Packaging: PyInstaller spec + build_companion.ps1 + GH Actions workflow; Settings serves source zip download + pairing UI w/ live status. ✓: zip download works; exe build documented (deferred: no Windows in build env — D8).
- [x] 9.5 Unraid: unraid-template.xml (port 5643, /data→/mnt/user/appdata/promptforge, icon, description), PUID/PGID/TZ entrypoint handling, idle-RAM check. ✓: template validates (xmllint), entrypoint chowns as PUID.
- [x] 9.6 (done early, Phase 4) Discord "What gets posted" rules panel: modes, filters, delivery (individual/digest), channel routing, throttle, 24h preview endpoint. ✓: rules engine tests every mode+filter+routing+digest+throttle; preview test.
- [x] 9.7 Rules UI panel in Settings→Discord. ✓: manual smoke.
- [x] 9.8 Phase gate; commit `phase-9 complete`.

## Phase 10 — quality bar
- [x] 10.1 Full pytest suite green, no skips-as-workaround, no xfail dodges. ✓: `pytest -q` all pass.
- [x] 10.2 `npm run build` clean (no TS errors); UI checked at desktop + 375px.
- [x] 10.3 (via sandbox image variant per D50 — real Dockerfile ships unmodified) `docker compose up --build`: healthcheck passes; `/` serves gallery; live Civitai scrape ingests real posts E2E; media compressed + thumbs; detail renders; stats populate model knowledge file; template renders form + assembles prompt.
- [x] 10.4 LLM live pass: no cloud key in build env; mocked verification in tests + REAL companion→Ollama bridge tested live (pair, proxy, offline). 
- [x] 10.5 Failure paths: boot with empty .env (runs, Needs-setup states, no crash); network kill mid-scrape (job error logged+shown, app up).
- [x] 10.6 README.md: Unraid install path, Windows/PowerShell dev quick-start, capture_login walkthrough, companion download+pair, Baserow/Discord hookup, adapter-stub extension guide, launch checklist of what was verified.
- [x] 10.7 Companion verified: pairs against running container and proxies mocked Ollama (exe build deferred per D8 — source-run verified).
- [x] 10.8 Design polish pass (empty states, focus, motion restraint, no ad-hoc hex). 
- [x] 10.9 Final commit `phase-10 complete — v1.0`.

## Phase X1 — X.com adapter (freeform parsing, browser-based)
- [x] X1.1 capture_login.py `x` target; XAdapter skeleton (BrowserAdapter, requires_auth, session status, GraphQL wants_response). ✓: session status flows to /api/scrapers.
- [x] X1.2 x_text.py deterministic prompt/model extraction (labels, fences, quotes, model keywords, hashtags, t.co strip, confidence high/low). ✓: unit tests hits+misses.
- [x] X1.3 GraphQL tweet parsing: walk timeline JSON → media variants (highest quality: orig photos, top-bitrate mp4), text, author, engagement, reply/quote handling; one Post per media item (tweet id dedupe key). ✓: fixture tests.
- [x] X1.4 Scope controls (settings): search terms, max/run, min engagement, media filter, skip replies; fetch_recent rotates terms via X search crawl. ✓: filter tests.
- [x] X1.5 Low-confidence prompts weighted down by knowledge engine (stats+analysis skip low-conf text; post still counted). ✓: pytest.
- [x] X1.6 Registry + Settings UI (X source card: session status, scope controls); ToS note in README. ✓: /api/scrapers lists x; manual smoke.
- [x] X1.7 Phase gate: full suite green; commit `phase-X1 complete`.

## Phase X2 — follow list / page monitoring
- [x] X2.1 monitored_accounts table + handle normalization (@handle / bare / profile URL, bulk paste). ✓: unit tests.
- [x] X2.2 monitoring.py: run_account (timeline via XAdapter.fetch_account, stop at last_post_id cursor, advance after ingest), per-account auto-tag + auto-collection (family scoping respected), failure isolation. ✓: pytest w/ mocked adapter.
- [x] X2.3 Scheduler tick (due accounts by interval, serialized with scrape lock) + pause/resume-all. ✓: pytest.
- [x] X2.4 Monitoring API: list w/ status, bulk add, patch, delete (posts kept), run-now, pause/resume-all. ✓: pytest.
- [x] X2.5 Monitoring UI: account cards (handle, last-checked, new-since, status), add box w/ bulk paste, per-account controls, recent-finds strip, run-now. ✓: manual smoke.
- [x] X2.6 Phase gate; commit `phase-X2 complete`.

## Phase X3 — Grok integration (find, curate, monitor)
- [x] X3.1 integrations/grok.py: xAI OpenAI-compatible client (chat + live X search params), test_connection (validate key, list models), own daily budget + usage counters. ✓: mocked tests incl. failure modes.
- [x] X3.2 "grok" selectable as knowledge-engine LLM provider (factory case, budget applies). ✓: pytest.
- [x] X3.3 Discover creators: POST /api/grok/discover {interest} → reviewable candidates (reason+sample), de-duped vs monitored; add-to-follow-list flow (added_by=grok, never silent). ✓: mocked tests.
- [x] X3.4 Curate: batched budgeted pass over fresh X posts → ai-media check, inferred-vs-stated model, technique/tag suggestions written to existing fields; scheduler job; no-op without key. ✓: mocked tests.
- [x] X3.5 Digest: periodic Grok summary of monitored accounts (new+notable, trending models/techniques) surfaced in-app + optional Discord routing. ✓: mocked tests.
- [x] X3.6 Settings UI: X.com & Grok group (session+scope, Grok key/test/model picker, per-feature toggles+budgets, monitoring defaults). ✓: manual smoke.
- [x] X3.7 Phase gate; commit `phase-X3 complete`.

## Phase X4 — quality bar for the X feature
- [x] X4.1 Full suite green (all new tests: parser hits/misses, variants, dedupe, cursor, failure isolation, auto-tag/collection, grok mocked paths + key-missing no-ops). ✓: 159 passed.
- [x] X4.2 npm build clean; monitoring + settings UI checked desktop+mobile. ✓: `✓ built in 2.55s`; Playwright screenshots at 1440px + 375px (Monitoring w/ seeded ok/grok/not-found accounts + recent finds, Settings X+Grok cards); switch-knob overlap found by geometry measurement and fixed (`left-0` on knob spans in ScrapersPage/MonitoringPage/SettingsKit).
- [x] X4.3 Live smoke: no X session/key exists in this sandbox (and art-site egress is blocked, D46), so per spec the mocked paths ran: seeded-server demo + test_monitoring cursor test both push account-poll posts through the real pipeline (download → compress → thumbs → FTS → knowledge exclusion); documented in README launch checklist — first live poll with the user's own session is a first-boot step.
- [x] X4.4 README updates (X session capture, monitored accounts, Grok enablement, ToS note — "logged-in scraping is subject to X's ToS and your own account is the thing at risk; keep polling gentle"). ✓: new "X.com: monitored creators + Grok curation" section, Collects blurb, 159-test count, launch-checklist entry.
- [x] X4.5 Final commit `phase-X4 complete — X feature v1`.

## Phase X5 — one-click connect (X login in-app + Grok quick-connect)
- [x] X5.1 Backend connect manager (`scrapers/connect.py`): server-side headless Chromium login — WS screencast (JPEG frames) + forwarded mouse/keyboard/scroll/paste, auto-save on X `auth_token` cookie (idle-tick detection so input bursts land first), manual "save now" for other browser sites, single-session lock, idle/hard timeouts, same-origin WS (mismatch → 4403), lazy Playwright import. ✓: 6 fake-driven protocol tests (auto-save incl. expired-flag clear, manual save, busy/unknown/no-stack, origin reject+allow, hard timeout, env URL override).
- [x] X5.2 Session REST: upload storage_state JSON (shape-validated, 2MB cap) + disconnect per browser adapter; expired flag cleared on install. ✓: pytest.
- [x] X5.3 Real-Chromium integration test (importorskip where Playwright absent, D5): full WS protocol against a local stand-in login page — click/typed key events/Enter → auth_token cookie → auto-saved session file. ✓: green here with real Chromium 141 (PF_CHROMIUM_PATH).
- [x] X5.4 Frontend: ConnectModal (canvas screencast, input/paste/scroll forwarding, save/cancel), "Connect X account" on the X card + Monitoring banner, Connect/Disconnect on all tier-2 scraper cards, upload fallback, Grok quick-connect ("Get an API key ↗" + paste → auto-save → auto-test → live model picker). ✓: build clean; Playwright drove the real UI end-to-end against the stand-in login (typed password visible in the streamed frame, auto-save, card flips Connected ✓, toast) + Grok paste-to-connect against a local xAI stand-in (badge + 3-model picker); mobile 375px modal checked; zero page errors.
- [x] X5.5 Docs (README one-click section + launch-checklist entry, CLAUDE.md D56–D58) + full suite green (167). Commit `phase-X5 complete — one-click connect`.

## Phase X6 — one-click connect for every source
- [x] X6.1 Backend: `auth_kind` per adapter (session / api_key / none) surfaced by `/api/scrapers` with `session_optional`, `connectable`, `key_configured`, `key_setting`, `key_url`; session status reported for ALL browser sites (login optional ones included); login auto-detection for every site — known cookie markers (X `auth_token`, Midjourney `Midjourney.AuthUserToken`) finish the flow, everything else uses generic detection (a new auth-looking cookie/localStorage key after the user's first input → non-final save, window stays open); Civitai `test_connection` + `POST /api/scrapers/{name}/test`; stale "run capture_login.py" status texts now lead with Connect. ✓: 5 new tests (generic detection incl. csrf/analytics noise ignored + localStorage trigger + re-save, Midjourney marker finishes, auth-name classifier, adapter auth fields, Civitai test modes 401/200/unreachable + lexica 404) — 172 green.
- [x] X6.2 Frontend: Connect/Reconnect/Disconnect on every browser-site card (optional ones labelled), modal handles non-final saves (green banner + "Done"), Civitai paste-to-connect (Get key ↗ + auto-save + auto-test + Remove key) in Settings and inline on its Scrapers card, "no login needed" chip for Lexica. ✓: build clean; Playwright through the real UI against stand-ins — dashboard shows every source's connect state, Civitai inline paste → "✓ Key accepted" → "API key: connected", TensorArt modal login → "Login detected — session saved ✓" + Done → "Login session: valid"; zero page errors.
- [x] X6.3 Docs (README connect-everywhere section + launch-checklist entry, CLAUDE.md D59–D60) + full suite green (172); commit `phase-X6 complete — one-click connect everywhere`.

## Phase I1 — Inspiration envelope, migration, scoring, dedupe, queue (backend)
- [x] I1.1 Additive schema migration (`db.migrate_schema`: PRAGMA table_info vs models → ALTER TABLE ADD COLUMN; never drops). ✓: legacy-shaped DB upgrades in place, rows intact.
- [x] I1.2 Layered post envelope: `ScrapedPost.observed` (author/engagement/text/media/relations/identity) → Post JSON columns `observed`/`enrichment`/`analysis`/`assertions` + indexed scalars (candidate/inspiration scores, ai_status/confidence, content_hash, phash, engagement_total, creator_id, has_workflow, prompt_source, model_source, pipeline_state, discovered_at); `engagement_snapshots` table. ✓: pytest.
- [x] I1.3 Deterministic Candidate Score (pre-download gate) + Inspiration Value Score (post-ingest) with configurable weights + breakdowns. ✓: formula tests.
- [x] I1.4 Dedupe levels: exact id (existing) + sha256 content hash + 64-bit dHash near-dup → `post_links` (link, never delete). ✓: resized/recompressed duplicate detected.
- [x] I1.5 `pipeline_jobs` queue (stage/state/priority/attempts/cost) + scheduler tick + central budgeted analysis dispatcher; ingest enqueues ENRICH/ANALYSIS for high-value posts only. ✓: pytest state machine.
- [x] I1.6 Phase gate; commit `phase-I1`. ✓: 180 tests green.

## Phase I2 — Generation metadata parsers
- [x] I2.1 A1111 full (LoRA/ControlNet/VAE/hires/denoise), ComfyUI workflow graph (model/loras/controlnet/sampler/scheduler/seed/cfg/size/video nodes), NovelAI, InvokeAI, EXIF UserComment/XMP, video sidecars; raw metadata preserved untouched under `params._raw_metadata`. ✓: fixtures + tests.
- [x] I2.2 Phase gate; commit. ✓: 187 tests green.

## Phase I3 — Extraction, classification, provenance, knowledge separation
- [x] I3.1 `intel/extract.py`: deterministic prompt/model/technique extraction with method+confidence+provenance → `assertions`; model alias table expanded (current image/video models); technique taxonomy expanded (camera/lighting/motion/format). ✓: tests.
- [x] I3.2 AI classification (ai_status 5-level + confidence + reason + source) + AI extraction only for unresolved high-value records via the central budget; never overwrites explicit data; uncertain never deleted. ✓: mocked LLM tests.
- [x] I3.3 Knowledge Engine: observed/inferred/AI separation (only high-confidence into canonical stats), expanded stats (prompt length, terminology, camera/lighting vocab, aspect ratios, engagement-weighted, temporal). ✓: tests.
- [x] I3.4 Phase gate; commit. ✓: 193 tests green.

## Phase I4 — Source capabilities, enrichment, X improvements, source metrics, snapshots
- [x] I4.1 Adapter `capabilities` flags + optional `fetch_detail/fetch_author/fetch_comments/fetch_related`; Civitai detail/author; X thread/quote/reply relations, alt text, links, variants, engagement, author details, TweetDetail comments (fixture) for high-value only. ✓: fixture tests.
- [x] I4.2 Source efficiency metrics per run (discovered/kept/enriched/prompt+metadata yield/dup rate/AI rate/LLM cost/reliability) → priority recommendation (never auto-disable). ✓: tests.
- [x] I4.3 Sanitized raw snapshots (optional setting) under DATA_DIR/snapshots. ✓: secrets stripped test.
- [x] I4.4 Phase gate; commit. ✓: 202 tests green.

## Phase I5 — Creators, Grok evidence, Grok Web session, Social accounts UX
- [x] I5.1 `creators` table + intelligence aggregation (followers, avg engagement, cadence, AI ratio, prompt availability, models, techniques, top/recent posts, trajectory); monitored_accounts linked; API. ✓: tests.
- [x] I5.2 Grok discovery evidence model (candidate → verify via adapter → store evidence → analyze; LLM output never authoritative) + richer discover output (evidence/models/content type/engagement estimate/confidence). ✓: tests.
- [x] I5.3 Grok Web session via existing connect flow (platform "grok", clearly ≠ API key, status/disconnect) + Settings "Social accounts" group (X / Grok Web / Grok API) with feature-level credential requirements. ✓: tests + screenshot.
- [x] I5.4 Phase gate; commit. ✓: 206 tests green; Social accounts card + Monitoring evidence/creator lines screenshotted desktop + 375px.

## Phase I6 — Search syntax, clusters, similarity, trends, inspiration API
- [x] I6.1 Search qualifiers: has:, creator:, technique:, camera:, after:, before:, engagement:>, inspiration:>, ai:, model_source:. ✓: parser + filter tests.
- [x] I6.2 Clusters (deterministic rules over topic/model/technique/style/creator/media/prompt pattern/camera/palette/subject/engagement) + membership + pages. ✓: tests.
- [x] I6.3 Similarity: visual (phash hamming), prompt (token Jaccard + FTS), technique-related, best-for-model. ✓: tests.
- [x] I6.4 Trend intelligence (weekly series for models/techniques/styles/terms/creators/topics/formats) + optional grounded LLM summary. ✓: tests.
- [x] I6.5 `/api/inspiration/*` routes (search, sources, queue, analytics, clusters, similar, enrichment, creators). ✓: tests.
- [x] I6.6 Phase gate; commit. ✓: 212 tests green (the I6 commit subject says 220 — typo; suite was 212).

## Phase I7 — Inspiration UI
- [x] I7.1 Inspiration section (nav) with tabs: Overview (sources w/ status, last/next run, discovered/kept/enriched/analyzed, errors, queue; Run/Pause/Resume), Sources (existing Scrapers), Creators (existing Monitoring + intelligence), Clusters, Queue/Errors, Analytics. ✓: screenshots. Done: `pages/InspirationPage.tsx` (Overview/Sources/Creators/Clusters/Queue/Analytics + cluster/creator detail routes), nav restructured (Gallery · Collections · Models · Inspiration · Studio · Settings), legacy /scrapers + /monitoring redirect; Playwright shots desktop + 375px, zero page errors.
- [x] I7.2 Post detail: "Why this is inspiring" score breakdown, detected fields, structured generation metadata, evidence/provenance, actions (Save/Favorite/Collection/Use in Studio/Use as Inspiration/Find Similar/View Creator/View Related). ✓: screenshots. Done: `components/IntelPanel.tsx` inside the DetailDrawer (score bars + breakdown, AI status, detected chips, generation metadata view, evidence toggle, thread/comments, clusters/links, Find similar thumbs that navigate inside the drawer), Studio Enhance handoff via localStorage context (`?inspiration=1`) with Insert structure / Use source prompt / attribution.
- [x] I7.3 Phase gate; commit. ✓: build clean, 212 tests green.

## Phase S1 — Film Studio data model + asset services
- [x] S1.1 Tables: film_projects, film_scenes, film_shots, film_assets, film_asset_versions, film_asset_refs, film_shot_assets, film_takes, film_events (decision log), film_gates, film_clips (footage corpus), film_jobs (checkpoints). Additive migration. ✓: tests. Done: `film/models.py` on the shared Base (db registers it), legacy-DB test proves the tables appear on boot.
- [x] S1.2 AssetService/VersionService/ReferenceService: immutable versions, restore/duplicate/compare/use-as-current, uploads preserved under DATA_DIR/film (safe ids, traversal-proof), import from gallery, canonical visual context JSON with locks/variables/continuity/negatives. ✓: tests. Done: `film/assets.py` (copy-on-write versions, freeze-on-use, propagate selected/future/project, delete guard), `film/refs.py`, `film/context.py`, `film/attributes.py` (per-type schemas + lock groups + ref kinds), `film/projects.py` (project/scene/shot CRUD + exact pins + effective assets), `api/film.py` (39 routes), `/film-media` mount.
- [x] S1.3 Phase gate; commit. ✓: 219 tests green.

## Phase S2 — Story, Director, storyboard logic, timing, continuity, gates
- [x] S2.1 Story/script model (project → scenes → shots), import/edit; DirectorService (direct story/scene/shot, production plan, shot durations by pacing profile) via central LLM with structured JSON + deterministic fallback; proposals applied only on Accept; locked props never changed. ✓: mocked tests. Done: `film/story.py` (slugline/heading/paragraph parser, import replace/append), `film/presets.py` (18 shot types, lenses, moves, lighting, pacing, pipeline templates, user favourites/overrides), `film/director.py` (proposals stored as film_jobs; LLM via run_llm with fallback; catalog-based cost estimates; accept/reject; locked keys blocked).
- [x] S2.2 ShotContextBuilder: scene defaults + explicit overrides + locks → effective context → prompt; version pinning; update selected/future/all shots. ✓: tests. Done: `film/shotctx.py` (preset → scene → shot layering with per-field sources, canonical asset contexts with exact versions, deterministic prompt/negative, regeneration change/preserve with locked groups blocked).
- [x] S2.3 TimelineService: shot durations, scene gaps (project default + per-scene override + apply-all/reset), transitions separate from gaps, timecode recalculation, runtime. ✓: tests. Done: `film/timeline.py` (dissolve/wipe overlap only when no gap; fades/cuts never shift timecodes).
- [x] S2.4 ContinuityService (adjacent shot checks, flexible/balanced/strict modes), gates (plan/assets/storyboard/rough cut/QA; reject invalidates only dependents), decision log, checkpoints/resume. ✓: tests. Done: `film/continuity.py`, `film/gates.py` (snapshots + stale detection), `film/board.py` (Backlot stages derived from state + replay), `film/jobs.py` (checkpointed pause/resume/cancel/recover runner).
- [x] S2.5 Phase gate; commit. ✓: 228 tests green.

## Phase S3 — Generation, media strategy, cost, QA, repair, export, audio/subtitles, footage, reference video
- [x] S3.1 Provider capability matrix (modes per family/provider in pricing catalog) + provider scoring service + cost estimate→reserve→execute→reconcile with project budget modes. ✓: tests. Done: pricing.json `modes` (image_to_image/reference_to_image/image_to_video/start_end_to_video with provider input names; additively merged into user copies), `film/capabilities.py`, `film/scoring.py` (task fit/quality prior/controllability/consistency/history reliability/cost/latency with basis), `film/costs.py` (observe|warn|approve|cap, reserve/reconcile events).
- [x] S3.2 Takes: generate start/end frames + video via the existing generation queue, multi-take preserved, previous-shot last frame → next start frame (ffmpeg last-frame extraction), targeted regeneration (preserve/change sets → context). ✓: tests with mocked providers. Done: `film/takes.py` (one Generation row per take, `_film_take_id` hook in `generation/queue.py`, adapters accept image inputs via `_inputs`/`_input_map`, richest-mode selection, chaining, frame upload/post/ref/lock, imports, compare, sync_pending), `film/production.py` (sample + batch runs as checkpointed jobs gated by plan/storyboard approval).
- [x] S3.3 Media strategy per shot (AI video / image+animation / user footage / stock / archival / motion graphics / still) + footage corpus (user upload analysis via ffprobe/scene-cut/keyframes; Pexels/Pixabay/Unsplash/Archive.org when keys configured, mocked) + motion-graphics title cards (Pillow+ffmpeg). ✓: tests. Done: `film/footage.py` (6 sources incl. NASA + Wikimedia, license kept as reported, corpus search with confidence + segment timecodes, attach/trim), `film/graphics.py` (cards, lower thirds, captions, Ken Burns stills).
- [x] S3.4 Audio tracks + capability flags, subtitles (SRT/VTT/burn-in, editable, re-sync), QA (ffprobe technical, black/frozen frame heuristics, continuity) → PASS/WARN/FAIL + repair queue tied to smallest artifact; export (ffmpeg concat with gaps/fades/xfade, audio mix, subtitles) + post-render review. ✓: tests with tiny generated media. Done: `film/audio.py`, `film/subtitles.py` (script-derived cues anchored to shots), `film/qa.py`, `film/export.py` (conform → concat/xfade groups → amix → burn-in → sources.json → review), tables film_audio_tracks/film_subtitles.
- [x] S3.5 Reference-video director mode (ffprobe/scene detection/keyframes/pacing/aspect; optional transcript/LLM) → grounded production proposal requiring approval. ✓: tests. Done: `film/reference.py` (upload/post/clip; URL needs yt-dlp and says so; transcript/OCR reported unavailable), `reference_proposal` accepted through the Director path.
- [x] S3.6 `/api/film/*` routes. ✓: tests. Phase gate; commit. ✓: 111 film routes, 237 tests green.

## Phase S4 — Film Studio frontend
- [x] S4.1 Film section nav (Projects/Assets/Story/Director/Storyboard/Timeline), AssetsPage (tabs, visual editors incl. Character/Location with lock toggles, references upload/import, versions, AI tools), AssetPicker. ✓: screenshots. Done: `pages/film/FilmPage.tsx` (section shell + current-project context), `ProjectsPage.tsx` (Backlot board, gates, cost, settings, decision log), `AssetsPage.tsx` (schema-driven editors with 🔒 groups, references drag/drop + gallery import, versions restore/duplicate/compare/use, AI tools gated by capabilities, usage + propagation), `components/film/AssetPicker.tsx`; backend `film/asset_gen.py` (+2 routes) for asset Generate/Variation/Edit → references.
- [x] S4.2 StoryPage + DirectorPage (production plan, reference video, direct story/scene/shot with Accept/Reject/Edit, sample run, Backlot board, gates, decision log, cost). ✓: screenshots (`film-story.png`, `film-director.png`).
- [x] S4.3 StoryboardPage (navigator/grid/inspector/strip, shot cards, contact sheet, timing panel w/ gaps, visual shot-type library, visual camera + lighting controls, basic/advanced/expert drawers, takes/compare, repair, start/end frames, continuity inspector). ✓: screenshots (`film-storyboard.png`, `film-contact-sheet.png`, `film-shot-types.png`, `film-inspector-advanced.png`, `film-inspector-expert.png`). Components: `ShotTypeLibrary.tsx` (SVG diagrams), `CameraControls.tsx`, `LightingPanel.tsx` (draggable key/fill/rim), `FootageModal.tsx`.
- [x] S4.4 TimelinePage (proportional timeline, drag durations, gaps, audio tracks/mixer, subtitles, QA report, export). ✓: screenshots (`film-timeline*.png`). `components/film/TimingPanel.tsx` exports pure helpers (runtimeOf/widthFor/snapDuration) for unit tests.
- [x] S4.5 Inspiration → Studio/Film "Use as Inspiration" handoff with provenance. Phase gate; commit. ✓: IntelPanel “🎬 Use in Film” → `/film/storyboard?inspiration=1` banner applies camera/lighting/style/subject/techniques to the selected shot with `overrides.inspiration` attribution (`film-inspiration-handoff.png`); zero page errors on desktop + 390px; build clean; 238 backend tests.

## Phase S5 — Frontend tests + acceptance journey
- [x] S5.1 vitest + testing-library for timing math, context/lock helpers, ShotTypeLibrary, AssetPicker. ✓: green. Done: `vitest.config.ts` (jsdom), `src/test/setup.ts`, `npm test` → 19 tests (`lib/film.test.ts`, `TimingPanel.test.tsx`, `ShotTypeLibrary.test.tsx`, `AssetPicker.test.tsx`).
- [x] S5.2 Scripted acceptance journey (spec AL) through the real app with mocked providers; restart persistence; desktop + mobile screenshots. ✓: passes. Done: `tests/test_film_acceptance.py` (project → script → assets/locks/refs → plan → Director scenes/shots → visual shot type → gaps/runtime → camera+lighting → frames → chaining → sample → gates → batch → alternates → continuity → audio/subtitles → QA → export → restart → persistence) + Playwright `film_journey.mjs` (library pick, duration, gap default/override/reset, lens+lighting, continuity, QA, lock → new version) with zero page errors; screenshots `film-*.png` desktop + 390px.
- [x] S5.3 Phase gate; commit. ✓: 239 backend + 19 frontend tests green.

## Phase S6 — Docker verification + docs + final gate
- [x] S6.1 Docker build/start (sandbox variant per D50) → health, migrations on an existing DB, Gallery/Studio/Inspiration/Film pages, persistence after restart. ✓: documented. Done: `scratchpad/docker_smoke.sh` — image built; booted on the seeded film data (healthy; 19 endpoints incl. Film/Gallery/Studio/Inspiration/scrapers/Grok/settings all 200; export file served; `/data` 99:100; `docker restart` keeps 7 shots + approved plan), on an empty dir (healthy, film dirs created, project creation works), and on a legacy-shaped DB with film tables/columns removed (`schema migrated` on boot, tables/columns re-added, rows kept); Playwright screenshots of every Film page served by the container (`docker-film-*.png`, zero page errors).
- [x] S6.2 README/CLAUDE.md/PROGRESS updates; full regression suite; final commit + push. ✓: README Film Studio section + launch checklist (v2.0/v2.1) + test counts; CLAUDE D73–D79; 239 backend + 19 frontend tests green.

## Forge — model-aware prompt engineering + execution platform (one-shot spec, phases F1–F9)
- [x] F1 Audit + plan: baseline suite green (239 backend + 20 frontend), `docs/architecture-forge.md` (existing/new architecture, boundaries, migration, flags, fallback), `docs/integration-ideas.md` (§16/§21 registry). ✓: docs committed.
- [x] F2 Model Intelligence Registry: `models_catalog.json` (seed → DATA_DIR copy, additive merge) + `forge/catalog.py` (normalized entries, capability resolver, parameter validator, recommendations input) + `/api/forge/models*`. ✓: 4 tests (seed lifecycle, additive merge, validator, registry merge). Done: `forge/catalog.py`, `api/forge.py`, seed `models_catalog.json` (15 families, full §2 schema, honest nulls).
- [x] F3 Intent + router + prompt compiler: `forge/intent.py` (deterministic, evidence-tagged), `forge/router.py` (ranked, explainable, overridable; §12 policy), `forge/compiler.py` (PromptPackage, recompile on model switch). ✓: 6 tests (spec example, genre-vs-orientation, explainable ranking with reported unsupported constraints, per-model compilation differences, LLM-optional). Done: `forge/intent.py`, `forge/router.py`, `forge/compiler.py`, `/api/forge/{intent,route,compile}`.
- [ ] F4 Tool layer + fallback: `forge/tools.py` typed tools over the generation queue; generation start factored into a service; opt-in one-step fallback recorded on the job. ✓: tests with mocked providers.
- [ ] F5 Test Lab + evaluation: prompt_experiments/prompt_variants/variant_runs tables; deterministic evaluator + optional LLM critique; refinement = new version with diff. ✓: tests.
- [ ] F6 Creative Plans: creative_plans/plan_assets; deterministic presets + optional LLM draft as a proposal; lock/regenerate/fork/reorder; execution through tools. ✓: tests.
- [ ] F7 Workflows: serialized node graph, validation, topological executor over tools + local ops, waiting_approval pause, templates incl. shorts_pipeline. ✓: tests.
- [ ] F8 Frontend Forge section: Compose (idea → intent → ranked models with reasons → package → generate), Catalog browser with capability badges, Lab (side-by-side runs, scores, versions/diffs), Plans, Workflows editor, Usage dashboard; provider settings free/local/fallback controls. ✓: build + vitest + screenshots.
- [ ] F9 Usage endpoint, docs (README), full regression, production build, docker sandbox smoke (D50), design preview + canvas re-capture (D80/D81), PROGRESS/CLAUDE close-out. ✓: all green, pushed.

## Next up
All planned phases (v1.0 → X1–X6 → I1–I7 → S1–S6) are complete: 239 backend + 19 frontend tests green, sandbox container verified. First-boot steps on the user's own network: live Civitai scrape, real X login through the connect modal, first AI take with a real fal.ai/Replicate/WaveSpeed key (see README launch checklist). Future work candidates: audio/TTS provider adapters (capability flags already in place), yt-dlp reference downloads, vision-model continuity checks.
