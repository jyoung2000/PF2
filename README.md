# PromptForge

**AI prompt intelligence, library & generation studio — self-hosted, one container, port 5643.**

PromptForge scrapes AI-art galleries for prompts + media, curates them into a
Pinterest-style library, *learns how to prompt every model it sees*, turns your
collections into visual prompt templates, and generates through fal.ai /
Replicate / WaveSpeed with the price shown before you spend a cent. Results
feed back into the knowledge engine, so it gets smarter forever. A free,
self-hosted alternative to morphic.com's visual workflows, with browsing in the
spirit of Pinterest and eyecannndy.com.

- **Collects** — Civitai + Lexica out of the box (plain API, zero setup); Midjourney
  Explore, TensorArt, SeaArt, PixAI and X.com via a stealth browser engine with your
  login session — X adds a per-creator follow list and optional Grok curation.
  Media is lossy-compressed (WebP / H.264) with thumbnails; embedded generation
  metadata (A1111 / ComfyUI PNG chunks) is parsed *before* compression.
- **Curates** — masonry gallery with blur-up thumbs and hover-playing videos,
  full-text search (`tag:cyberpunk model:flux` qualifiers), favorites, custom
  tags, model-scoped collections, automatic per-model collections, technique facet.
- **Learns** — a per-model knowledge file (markdown, capped 16KB) built from
  free deterministic stats on every ingest + budgeted LLM analysis (Anthropic /
  any OpenAI-compatible / Ollama / your desktop GPU via the companion app —
  local providers make learning free). Collections get style profiles; profiles
  become editable visual templates.
- **Creates** — Prompt Studio: template forms with live prompt assembly and
  reference-image slots, one-click Enhance (before/after with "why" notes),
  saved-prompt search across everything.
- **Generates** — connect fal.ai / Replicate / WaveSpeed; the price for every
  model×provider shows up front, routing auto-picks the cheapest connected
  provider, spend is tracked per provider, outputs land in the library and
  teach the engine.
- **Shares** — Baserow table sync (media files included) and a Discord bot
  (`/latest`, `/random`, `/search`) with a full "what gets posted" rules panel:
  modes, filters, digests, per-channel routing, throttle, 24h preview.

---

## Install on Unraid

1. Build or pull the image (until it's on a registry, build once on any
   Docker box: `docker build -t promptforge:latest .` then
   `docker save promptforge:latest | ssh root@TOWER docker load`).
2. Copy `unraid-template.xml` to `/boot/config/plugins/dockerMan/templates-user/`
   on your Unraid box (or add a container manually with the same values).
3. In the Unraid UI: **Docker → Add Container → PromptForge**. Defaults are
   correct out of the box:
   - Port **5643**
   - `/data` → `/mnt/user/appdata/promptforge`
   - `PUID=99` / `PGID=100` (nobody:users — files land with the right owner)
   - `TZ` to taste; `--shm-size=1g` is preset (Chromium needs it)
4. Start it and open **http://TOWER:5643** — the gallery, scrapers and settings
   are live immediately. Everything is configured from the GUI; a `.env` file
   is optional (GUI settings override it).

## Windows / PowerShell dev quick-start

```powershell
git clone https://github.com/jyoung2000/pf2.git promptforge
cd promptforge
copy .env.example .env        # optional — the app runs with an empty .env
docker compose up -d --build
start http://localhost:5643
```

Native development (hot reload):

```bash
bash scripts/dev_setup.sh                 # backend venv + frontend deps
cd backend && .venv/bin/uvicorn promptforge.main:app --port 5643 --reload
cd frontend && npm run dev                # Vite on :5173, proxies /api
cd backend && .venv/bin/python -m pytest  # 239-test suite
cd frontend && npm test                    # 19 vitest component/helper tests
```

## First hour with PromptForge

1. **Scrapers** page → Civitai is already OK → **Run now**. Posts stream into
   the gallery within a minute (watch the live log). Paste a Civitai API key
   (Connect on its card) for higher limits + NSFW.
2. Save a few favorites into a **collection** (🔖 on any card). Collections
   adopt the model family of the first post — that's what keeps styles
   coherent (a per-collection "allow mixed models" toggle exists).
3. **Settings → Knowledge engine**: pick an AI provider. Ollama or the
   companion app = free unlimited learning; cloud providers respect a daily
   call budget with a live usage counter.
4. **Studio**: your collection now has a generated template — fill the form,
   watch the prompt assemble, Enhance anything you paste.
5. **Settings → AI providers**: paste a fal.ai / Replicate / WaveSpeed key,
   hit Test, then Generate from the Studio — expected price is shown before
   every run.

## Logging into Midjourney (and other browser sites)

Every source connects in one click from its card on the Scrapers page:

- **Browser sites** (X, Midjourney required; TensorArt / SeaArt / PixAI
  optional — they scrape logged-out, a session just helps): click
  **Connect**, log in inside the streamed server browser, and the session
  saves itself. X and Midjourney finish the moment their login cookie appears;
  the others save as soon as a login is detected and leave the window open in
  case you weren't done ("Save session now" re-saves, "Done" closes).
  **Reconnect** / **Disconnect** live next to the status once connected, and
  an expired session says so on the card.
- **Civitai** is an API key instead: click **Connect** on its card (or use the
  Settings field), paste the key, done — it saves and tests itself.
- **Lexica** needs nothing.

The desktop route still works as a fallback for browser sites:

```bash
# on your desktop (needs a display):
pip install playwright && playwright install chromium
python scripts/capture_login.py midjourney
# log in in the window that opens, press Enter →  ./data/sessions/midjourney.json
```

Upload the exported file with the card's upload button (X card) or copy it to
`/mnt/user/appdata/promptforge/sessions/midjourney.json`. PromptForge never
solves captchas or evades blocks: if a site throws a challenge during a scrape,
the adapter logs it and backs off — and in the Connect window, *you* answer it.

## X.com: monitored creators + Grok curation

X posts carry no structured generation metadata, so PromptForge mines prompts
and model names straight out of tweet text — deterministically, with a
confidence flag: clearly labelled prompts ("Prompt:", code fences) count fully,
loose guesses stay on the post but are excluded from model learning so they
never pollute the knowledge files.

1. **Connect your account (one click)** — hit **Connect X account** in
   Settings → X.com source (or on the Monitoring page banner): a window
   streams your *server's own* browser, you log in exactly as usual — clicks
   and keystrokes go straight to the page, are never stored, and the moment
   the login lands the session saves itself to `/data/sessions/x.json`. If a
   verification step appears, you complete it yourself — PromptForge never
   automates or evades any of that. The same Connect button sits on every
   browser-site card (Midjourney & co use the modal's "Save session now"
   button once logged in). Fallbacks: upload an `x.json` exported by
   `python scripts/capture_login.py x` from your desktop, or copy that file
   to `/mnt/user/appdata/promptforge/sessions/x.json` by hand; a Disconnect
   button forgets the session any time (posts are kept).
2. **Search crawls** — the X card in Settings has its own search terms
   (`#midjourney, #AIart, #aivideo, #flux` by default), a minimum-engagement
   filter, images/videos/both, skip-replies, and a max-per-run cap. The site
   joins the normal scheduler rotation.
3. **Follow specific creators** — the **Monitoring** page: paste handles, @s,
   or profile URLs (bulk paste works — commas or one per line). Each account
   polls on its own interval with a per-account cursor, so only new posts are
   fetched. Per-account switches: media-only, auto-tag every find, auto-file
   into a collection (model-family scoping is honored, same as manual saves).
   Accounts fail independently — a renamed or dead account flips to "not
   found" on its row without stopping the rest, and pause-all/resume-all is
   one click.
4. **Optional: Grok (one paste)** — click **Get an API key ↗** on the Grok
   card (console.x.ai), paste it into the key field, done: pasting saves the
   key, runs the connection test, and loads the live model picker by itself:
   - **Discover** — describe an interest on the Monitoring page ("cinematic
     AI video creators") and Grok live-searches X for candidate accounts,
     each with a why-them note. Every candidate is review-before-add: you
     click Watch or Dismiss; nothing is ever followed silently.
   - **Curate** — a budgeted background pass over unreviewed X finds: flags
     AI-vs-not (non-AI posts are only marked, never deleted), fills in the
     model where the text didn't state one (marked *inferred*, never
     overwriting a *stated* model), and suggests technique tags (whitelisted
     against the fixed taxonomy) plus ordinary tags you can remove like any
     other. Daily call budget with a live counter.
   - **Digest** — a periodic "what your monitored creators posted" summary on
     the Monitoring page, optionally routed to Discord.
   - Grok is also selectable as the knowledge-engine AI provider (Settings →
     Knowledge engine), reusing the same key.

Heads-up: logged-in scraping is subject to X's ToS and your own account is the
thing at risk — keep polling gentle. The defaults are conservative (60-minute
account interval, 5-minute floor, one browser run at a time), and the adapter
backs off on rate limits like every other site.

## Film Studio: from an idea to an exported cut

The **Film** section turns PromptForge into a self-hosted AI film studio on top of the same providers, storage and settings you already use. Nothing here needs a new container or a second database.

1. **Projects** — create a film project; its Backlot board shows every stage (Concept → Story → Assets → Storyboard → Asset approval → Shot generation → Audio → Edit → QA → Export) derived from real state, plus approval gates, cost (estimate / spent / reserved / budget mode) and the decision log.
2. **Assets** — persistent Characters, Locations, Props, Vehicles, Outfits and Styles. Every attribute group can be locked 🔒 (face, hair, body … architecture, layout …); references are uploaded, imported from your Gallery or generated (Generate / Variation / Edit — enabled only when a connected provider declares the mode). Versions are immutable once a shot uses them: editing then creates the next version, old shots keep theirs, and *Update selected / future / entire project* pushes a version explicitly.
3. **Story** — paste a screenplay, markdown headings or plain prose; scenes are split deterministically (sluglines give location, time of day, weather and speaking characters).
4. **Director** — *Direct story / scene / shot* and *Draft plan* produce **proposals** (through your configured AI provider, or a deterministic breakdown when none is set up). Accept, reject or edit them; locked properties are never changed, and every choice lands in the decision log with its reason and cost basis. Optional: analyse a reference video (ffprobe, scene cuts, pacing, keyframes — never copied) and let the Director propose a grounded structure.
5. **Storyboard** — image-first shot cards, a contact-sheet mode with bulk approval, a visual shot-type library (18 diagrammed presets, favourites, custom), visual camera (framing, angle, lens strip, motion) and lighting (draggable key/fill/rim, presets) controls, per-shot media strategy (AI video, image + animation, your footage, stock/archival, motion graphics, still), start/end frames (upload, generate, gallery, *use previous shot's last frame*), takes with compare, targeted *Repair / regenerate* (change vs preserve), continuity warnings in flexible/balanced/strict modes.
6. **Timeline** — proportional strip with drag-to-resize durations, a project default scene gap with per-scene overrides (apply-all / reset), audio tracks with a simple mixer, subtitles (from the script's dialogue, SRT/VTT import/export, burn-in), pre-render QA with a repair queue, and export (conformed clips, gaps, dissolves and fades, mixed audio, sidecar SRT/VTT, a `sources.json` with every take's provenance) followed by a post-render review.
7. **Editor** — a professional multi-track NLE over the same data. *Build timeline from storyboard* materialises one clip per shot at the exact storyboard timing (scene gaps become empty track space; the storyboard itself is never touched); from then on the edit is yours: drag/move/trim with magnetic snapping (toggle + break-out), split at the playhead, plain and ripple delete, insert gap, marquee multi-select, markers, unlimited video/audio/caption tracks with mute/solo/lock, per-clip speed, fades, gain, effects (opacity, scale, position, rotation, crop, colour, blur) and transitions, caption clips burned into the master, a frame-accurate preview player (derived clock, safe areas, timecode, loop) that resolves the sequence exactly like the export does, keyboard shortcuts (press `?`), and server-side undo/redo that survives restarts — every edit is saved as it happens. A **review queue** collects finished takes for approve / reject / regenerate (budget-aware) / compare / swap-into-timeline, and selection syncs both ways with the storyboard. When a sequence exists it drives export: what you see is exactly what renders (dissolves hold the outgoing frame in place, so runtime never shifts).

Costs come from the pricing catalog (`pricing.json` → `/data/pricing.json`) and are shown as *unavailable* when no price exists. Provider capabilities (image→video, start/end frames, reference images) come from the catalog's `modes` per provider; TTS, music, SFX, talking heads and lip sync are reported as unsupported until an adapter declares them. Stock footage needs API keys (Pexels, Pixabay, Unsplash) while Archive.org, NASA and Wikimedia Commons work without; licenses are stored exactly as reported.

## Forge: model-aware prompt engineering

The **Forge** section turns a one-line idea into a generation-ready package:

1. **Compose** — type the idea ("a cinematic 15-second 9:16 sci-fi trailer
   with the same character across shots"). Forge extracts the intent (every
   inference cites the text that produced it), ranks the catalog's models with
   explained scores — task fit, capability fit, quality, your own success
   history, cost, latency — and compiles a model-specific prompt: tag-style
   with negative prompts for SDXL-class models, flowing natural language with
   camera vocabulary for Flux-class, constraints it can't express folded back
   into the prompt. Click any candidate to recompile the same intent for that
   model. Constraints a model can't meet (a 15s ask against a 10s cap) are
   said out loud and clamped, never silently dropped.
2. **Models** — the intelligence registry: capability badges, aspect ratios,
   durations, licensing and commercial-use notes, local-hardware needs, per
   provider prices with live connection state, plus what your own library has
   observed. Seeded metadata lives in `models_catalog.json`; your copy in
   `DATA_DIR` is editable and wins.
3. **Lab** — A/B prompt versions across models: run, score 1–5, keep winners,
   fork with lineage. *Evaluate & refine* checks what is verifiable (output
   aspect/duration/type, missing intent elements, conflicting styles) and
   proposes a revision as a **new version with a word-level diff** — your
   prompt is never overwritten. Vision-level judgement is reported as
   unavailable rather than guessed.
4. **Plans** — "launch campaign for my music player app" becomes an editable
   asset pipeline (hero → socials → banner → vertical video) with locks,
   dependencies (dependents receive the hero as a reference automatically),
   rerun-failed-only and branching.
5. **Workflows** — a node editor over plain JSON graphs: prompt → compile →
   generate → approve → animate → export, with condition branches, a human
   approval checkpoint, local ffmpeg clipping and honest per-node
   availability. Templates include idea→image, still→motion and a
   long-video→shorts pipeline.
6. **Usage** — every job's model, provider, cost, latency, success rate and
   fallback lineage, plus score-per-dollar from your Lab ratings.

Model facts carry provenance: each catalogue entry records where it came from
(a cited source, or an honest "seeded from general knowledge"), a confidence,
and any known deprecation — the router reports a deprecation as an unsupported
constraint instead of quietly recommending a sunsetting model.

### Multimodal tools and evaluation

Connect a provider that declares them and these run for real: image and video
upscaling, background removal, speech synthesis, transcription, audio
analysis, music/SFX, video→audio and text/image→3D. Audio, 3D and text results
land in an artifact store (they are not library posts) but keep the same job
lineage. MuAPI declares all of them out of the box; it is one provider among
several and nothing depends on it.

**Evaluation** looks at the actual result when an evaluator is available: a
vision-capable LLM (Anthropic, OpenAI-compatible, Grok) or MuAPI's vision
endpoint scores prompt adherence, composition, subject presence, quality,
consistency and typography with evidence and a confidence; video is sampled
into keyframes; audio is transcribed and compared to the script; 3D gets local
format checks. With no evaluator the report says *content was not judged*,
gives the reason, returns no score and drops confidence — it is never
simulated.

Everything degrades honestly: with no generation provider configured you can
still compose, compare models, build plans and workflows — execution says
exactly what to connect. Provider fallback is opt-in per job and always
visible (a new linked job, never a silent switch). The same operations are
exposed as typed tools under `/api/forge/tools` for agents/automation.

## The companion app (desktop GPU bridge)

Your server stays light; your gaming PC does the AI thinking, free.

1. **Settings → Companion → Download companion** (source zip).
2. On the PC (with [Ollama](https://ollama.com) running):
   `pip install -r requirements.txt` then
   `python app.py --server http://TOWER:5643 --code 123456`
   (code from **Generate pairing code**; the token is remembered afterwards —
   later runs are just `python app.py`).
3. Pick **Companion (desktop GPU)** as the AI provider. Jobs queue while the
   PC is away and drain when it reconnects; an optional toggle falls back to a
   cloud provider instead.

It connects *outbound* (LAN or Tailscale, no port forwarding), proxies Ollama
endpoints only — no file access, no shell. Windows tray build:
`powershell -File companion/build_companion.ps1` → `PromptForgeCompanion.exe`
(or the `build-companion-exe` GitHub Actions workflow). The .exe isn't
pre-built in this repo because the app is compiled per-machine by PyInstaller —
running from source is equivalent.

## Hooking up Baserow & Discord

Both live in **Settings** as guided cards with a real **Test connection**:

- **Baserow** — paste your instance URL (cloud default) + a *database token*
  (Baserow → Settings → API tokens, with create/read/update rights). Leave the
  table empty and the test auto-creates a `PromptForge` table with the full
  schema, writes a probe row and deletes it. Toggle auto-sync, or push
  per-post from the detail drawer. Media uploads use the compressed file.
- **Discord** — paste a bot token (Developer Portal → New Application → Bot),
  click the generated invite link (scopes + permissions pre-selected), pick a
  channel from the live dropdown, done. The "What gets posted" panel controls
  auto-posting: manual / all / favorites / collections / families / platforms,
  media + SFW + must-have-prompt filters, individual-or-digest delivery,
  per-channel routing rules, a throttle, and a live "would have posted N items
  in the last 24h" preview. Slash commands: `/latest`, `/random`, `/search`.

## Adding a new scraper site

One file, one line — the pipeline, GUI and schema pick it up automatically:

```python
# backend/promptforge/scrapers/newsite.py
from .base import ScrapedPost, SourceAdapter          # plain-HTTP site
# from .browser_base import BrowserAdapter            # or browser site

class NewSiteAdapter(SourceAdapter):
    name, label = "newsite", "New Site"
    def fetch_recent(self, s, client, limit=100):
        data = client.get("https://newsite/api/feed").json()
        return [ScrapedPost(platform=self.name, platform_post_id=str(i["id"]),
                            media_url=i["image"], prompt=i.get("prompt"))
                for i in data["items"]]
```

Register it in `backend/promptforge/scrapers/__init__.py` (`_adapter_classes`),
drop a fixture JSON in `backend/tests/fixtures/`, write a parser test. Rules:
deterministic parsing only (JSON/CSS/regex — the LLM never parses sites),
fail independently, never crash the app.

## Architecture, in one breath

FastAPI + SQLite (WAL, FTS5) + APScheduler; React 18 + Vite + Tailwind served
static; scrapers are pluggable `SourceAdapter`s feeding one pipeline
(normalize → dedupe → download → extract metadata → compress → store → learn →
auto-push); knowledge lives as capped markdown under `/data/knowledge/`
(export/import as `.pfpack`); generation providers are one-file adapters behind
a price-aware router; Discord/Baserow/companion are optional background
integrations. Everything configurable from the GUI at runtime.

## Launch checklist (what was verified for v1.0)

- ✅ 129-test pytest suite green: adapter parsers (fixtures for all 6 sites),
  pipeline (dedupe, pre-compression metadata, WebP/MP4 + thumbs), search
  (qualifiers, collection scope), collection scoping (cross-family rejection +
  mixed-model override), knowledge engine (create-on-first-sight, 16KB cap,
  budget, mocked-LLM analysis, technique tagging, pack round-trip), templates
  (schema→form→prompt round-trip, JSON+text export/import identical), Enhance
  (mocked + 409 unconfigured), generation (price math image+video,
  cheapest-provider routing, override, mocked provider APIs, E2E queue flow,
  no-double-charge), Baserow/Discord clients with every specific failure mode,
  rules engine (all modes/filters/routing/digest/throttle), companion
  (pairing, WS auth reject, request bridge, offline queue + drain).
- ✅ `npm run build` clean; UI checked at 1440px and 375px.
- ✅ Container built and booted; Docker healthcheck healthy; gallery served.
- ✅ End-to-end scrape inside the container (Civitai wire format): 7 posts
  including video — compressed WebP/H.264, thumbnails, embedded PNG-chunk
  prompt recovered, model knowledge files created with live stats, FTS search,
  template assembled. (The build sandbox blocks art-site egress, so the smoke
  run used a local stand-in speaking the exact Civitai API format — on your
  network the same run hits civitai.com live; it's the first thing to try.)
- ✅ Companion app: paired against the running server with a real 6-digit code,
  proxied a (mock) Ollama through the WebSocket bridge, clean offline
  detection, revoke closes the socket.
- ✅ Failure paths: boots with an empty `.env` (everything shows "Needs setup",
  nothing errors); network killed mid-scrape → adapter records the error, app
  and healthcheck stay green.
- ✅ `/data` files owned by `PUID:PGID` (99:100) for Unraid.
- ✅ X feature (v1.1, +30 tests → 159): tweet-text prompt/model extraction
  (labelled/fenced/quoted hits *and* the false-positive traps —
  sparkling≠kling, influx≠flux, pikachu≠pika), GraphQL capture parse from a
  saved fixture (full-res `?name=orig` photos, top-bitrate MP4, multi-image
  tweets split into one post per media, retweet unwrap, quoted-tweet prompts),
  scope filters, per-account cursor polls fetching only new posts, per-account
  failure isolation, auto-tag/auto-collection with family scoping,
  low-confidence prompts excluded from knowledge stats, and Grok
  discover/curate/digest against a mocked xAI server — including inferred-vs-
  stated model writes, technique whitelisting, budget stops, and clean
  "Needs setup" no-ops with no key. No X login session exists in the build
  sandbox, so the E2E smoke ran the mocked account-poll path through the real
  pipeline (download → compress → thumbs → FTS → knowledge); the first live
  poll with your own session is a first-boot step, same as the Civitai one.
- ✅ One-click connect (v1.2, +8 tests → 167): the in-app X login (server-side
  Chromium screencast over a same-origin WebSocket with forwarded input,
  auto-save on X's session cookie, manual save for other browser sites,
  busy-lock, idle/hard timeouts, cross-origin rejection) proven three ways —
  fake-browser protocol tests, a real-Chromium integration test driving the
  whole loop against a local stand-in login page, and a Playwright run through
  the actual UI (click Connect → type the password into the streamed page →
  session file written, card flips to Connected). Session upload/disconnect
  endpoints tested; Grok paste-to-connect verified in-browser against a local
  xAI stand-in (paste → saved → tested → live model list). x.com itself is
  unreachable from the sandbox, so the first real X login through the modal is
  a first-boot step; the desktop-capture and upload fallbacks remain.
- ✅ Inspiration Intelligence (v2.0, +40 tests → 212): additive schema
  migration proven on a v1.0-shaped database; layered post envelope with
  per-field provenance (user > observed/metadata > extracted > inferred > AI);
  every embedded generation-metadata format (A1111/Fooocus, ComfyUI API + UI
  graphs, NovelAI, InvokeAI, SwarmUI, EXIF/XMP, video tags + sidecars) parsed
  from fixtures with raw chunks preserved; candidate/inspiration scores with
  explainable breakdowns; sha256 + dHash dedupe links; a staged queue
  (enrich → analysis → knowledge) with deferral on budget; deterministic
  extraction of models/camera/lighting/techniques with evidence; LLM analysis
  that never overwrites explicit data (mocked); source metrics, sanitized
  snapshots, creator intelligence, Grok discovery as verifiable evidence,
  advanced search syntax, rule-based clusters, similarity without a vector
  DB, weekly trends; the Inspiration UI (Overview/Sources/Creators/Clusters/
  Queue/Analytics + the drawer's "why this is inspiring" panel) checked with
  Playwright at desktop and mobile widths.
- ✅ Film Studio (v2.1, +27 backend tests → 239, +19 frontend tests): film
  tables on the shared metadata (migration verified inside the container on a
  legacy-shaped DB — dropped tables/columns came back, rows kept); copy-on-
  write asset versions with freeze-on-use, restore/duplicate/compare/use-as-
  current and explicit propagation; traversal-proof references; script →
  scenes parser; Director proposals with deterministic fallback and mocked
  LLM; preset → scene → shot context with deterministic prompts; timeline
  maths (gaps vs transitions) and continuity modes; gates with dependency-
  only invalidation; takes through the real generation queue with mocked
  providers (frames, previous-frame chaining, targeted regeneration,
  alternates); footage corpus + six stock sources (mocked HTTP); local cards
  and stills; audio/subtitles; ffprobe/black/freeze QA + repair queue; real
  ffmpeg export with gaps, dissolves, fades, audio mix and burned-in
  subtitles, reviewed after render; reference-video analysis; a scripted
  spec-AL acceptance journey through the real app including a simulated
  restart; a Playwright click-through of the Storyboard/Timeline UI; the
  sandbox container booted on existing data, on an empty dir and on a legacy
  DB (all healthy, `/data` owned by PUID:PGID, export served, project state
  intact after `docker restart`). No AI video/image provider is reachable
  from the build sandbox, so the first real take with your own fal.ai /
  Replicate / WaveSpeed key is a first-boot step — the flow up to and after
  the provider call is exercised end to end.
- ✅ Connect everywhere (v1.3, +5 tests → 172): every source card carries its
  connect state — Connect/Reconnect/Disconnect on all five browser sites
  (optional logins labelled), Civitai key paste-to-connect with a real
  connection test (401 vs 200 vs unreachable, mocked), Lexica "no login
  needed". Login auto-detection covers every site: known cookie markers for X
  and Midjourney finish the flow; the rest use generic detection (a new
  auth-looking cookie/localStorage key after your first input → saved, window
  stays open) — proven with fake browsers, and through the real UI against
  stand-ins: Civitai inline paste → "Key accepted", TensorArt modal login →
  "Login detected — session saved", Done → "session: valid".
- ✅ Editor (E1–E8, +21 backend tests → 319, +12 frontend tests → 46): a
  professional multi-track timeline editor at Film → Editor over four
  additive tables (tracks/clips/markers/revisions, D61-migrated — verified
  in the container on a DB with the tables and the review column dropped);
  build-from-storyboard with literal positions; drag/trim/split/ripple/
  marquee/snapping/zoom/markers/track M-S-L; per-clip trim, speed, fades,
  gain, effects and burned caption clips, all honoured by the export through
  ONE shared resolver so the master matches the editor to the frame
  (ffprobe-verified: trims, retimes, gaps, in-place dissolves that never
  shorten runtime); server-side snapshot undo/redo that survives restarts;
  a generation review queue (approve/reject/regenerate/compare/swap) and
  two-way storyboard↔editor selection sync; nine reference editors studied
  with licenses checked first (`docs/editor-audit.md` — patterns only, no
  code copied). Verified live with Playwright journeys (zero page errors)
  and the sandbox container booted on seeded data, across `docker restart`,
  and on the legacy-shaped DB.
- ⏸ Deferred (documented): Windows `.exe` is built per-machine via the included
  PyInstaller script/workflow (no Windows builder in the dev environment);
  SeaArt + PixAI adapters are marked *experimental* in the GUI (their internal
  APIs shift often — they degrade gracefully and never take the app down).
