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
- [ ] 8.1 generation/base.py + fal.py + replicate_provider.py + wavespeed.py (submit/poll/download; test_connection D10). ✓: mocked tests per provider incl. error modes.
- [ ] 8.2 pricing.py: pricing.json seed (image per-image, video per-second×res), DATA_DIR copy, GUI-editable API. ✓: estimate math tests image+video.
- [ ] 8.3 router.py: cheapest-connected-provider auto-route + override + per-model price list for dropdown. ✓: routing tests.
- [ ] 8.4 Generate API: estimate → queue → worker → provider → download → ingest(origin=generated, links) → learn; WS progress; spend totals per provider; no double-charge on error. ✓: mocked E2E test.
- [ ] 8.5 Settings UI: AI Providers cards (fal/replicate/wavespeed) guided setup + test; spend totals. ✓: manual smoke.
- [ ] 8.6 Generate UI: from Studio + "Recreate" in drawer; recommended model preselected; price-per-model dropdown; off-recommendation note; queue progress. ✓: manual smoke (mock provider in dev).
- [ ] 8.7 Phase gate; commit `phase-8 complete`.

## Phase 9 — companion app + Unraid packaging + Discord rules panel
- [ ] 9.1 companion server side: pairing (code issue/verify TTL/single-use, token sha256, list/revoke), WS hub (auth, hello/models, request/response, heartbeat), llm_jobs queue + drain on reconnect + cloud fallback toggle. ✓: pytest incl. bad-token reject, queue+drain.
- [ ] 9.2 llm/companion_client.py implements LLM interface via hub. ✓: mocked-hub test.
- [ ] 9.3 companion desktop app: ws client, ollama proxy (tags/generate/chat ONLY), tray UX (pystray; --headless), start-with-Windows toggle, mini log, reconnect w/ backoff. ✓: pytest against mocked ollama + real server TestClient/live WS.
- [ ] 9.4 Packaging: PyInstaller spec + build_companion.ps1 + GH Actions workflow; Settings serves source zip download + pairing UI w/ live status. ✓: zip download works; exe build documented (deferred: no Windows in build env — D8).
- [ ] 9.5 Unraid: unraid-template.xml (port 5643, /data→/mnt/user/appdata/promptforge, icon, description), PUID/PGID/TZ entrypoint handling, idle-RAM check. ✓: template validates (xmllint), entrypoint chowns as PUID.
- [x] 9.6 (done early, Phase 4) Discord "What gets posted" rules panel: modes, filters, delivery (individual/digest), channel routing, throttle, 24h preview endpoint. ✓: rules engine tests every mode+filter+routing+digest+throttle; preview test.
- [ ] 9.7 Rules UI panel in Settings→Discord. ✓: manual smoke.
- [ ] 9.8 Phase gate; commit `phase-9 complete`.

## Phase 10 — quality bar
- [ ] 10.1 Full pytest suite green, no skips-as-workaround, no xfail dodges. ✓: `pytest -q` all pass.
- [ ] 10.2 `npm run build` clean (no TS errors); UI checked at desktop + 375px.
- [ ] 10.3 `docker compose up --build`: healthcheck passes; `/` serves gallery; live Civitai scrape ingests real posts E2E; media compressed + thumbs; detail renders; stats populate model knowledge file; template renders form + assembles prompt.
- [ ] 10.4 LLM live pass if key/Ollama present, else mocked verification documented.
- [ ] 10.5 Failure paths: boot with empty .env (runs, Needs-setup states, no crash); network kill mid-scrape (job error logged+shown, app up).
- [ ] 10.6 README.md: Unraid install path, Windows/PowerShell dev quick-start, capture_login walkthrough, companion download+pair, Baserow/Discord hookup, adapter-stub extension guide, launch checklist of what was verified.
- [ ] 10.7 Companion verified: pairs against running container and proxies mocked Ollama (exe build deferred per D8 — source-run verified).
- [ ] 10.8 Design polish pass (empty states, focus, motion restraint, no ad-hoc hex). 
- [ ] 10.9 Final commit `phase-10 complete — v1.0`.

## Next up
Phase 8, task 8.1 (generation providers).
