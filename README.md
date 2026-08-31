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
cd backend && .venv/bin/python -m pytest  # 159-test suite
```

## First hour with PromptForge

1. **Scrapers** page → Civitai is already OK → **Run now**. Posts stream into
   the gallery within a minute (watch the live log). Add a Civitai API key in
   Settings for higher limits + NSFW.
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

Tier 2 sites scrape through a stealth Chromium with *your* login session:

```bash
# on your desktop (needs a display):
pip install playwright && playwright install chromium
python scripts/capture_login.py midjourney
# log in in the window that opens, press Enter →  ./data/sessions/midjourney.json
```

Copy the exported file to your server at
`/mnt/user/appdata/promptforge/sessions/midjourney.json`. The Scrapers page
flips to "session: valid" and the adapter goes live. Same flow for
`tensorart`, `seaart`, `pixai` (those work logged-out too; a session just
helps). If a session expires the dashboard says so — re-run the script.
PromptForge never solves captchas or evades blocks: if a site throws a
challenge, the adapter logs it and backs off.

## X.com: monitored creators + Grok curation

X posts carry no structured generation metadata, so PromptForge mines prompts
and model names straight out of tweet text — deterministically, with a
confidence flag: clearly labelled prompts ("Prompt:", code fences) count fully,
loose guesses stay on the post but are excluded from model learning so they
never pollute the knowledge files.

1. **Capture a session** — X requires login; it's the same flow as Midjourney:
   `python scripts/capture_login.py x`, log in in the window, press Enter →
   `./data/sessions/x.json`, copy to
   `/mnt/user/appdata/promptforge/sessions/x.json`. The X card on the Scrapers
   page and the Monitoring-page banner flip to "session: valid".
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
4. **Optional: Grok** — paste an xAI API key (console.x.ai) in Settings →
   Grok and hit Test:
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
- ⏸ Deferred (documented): Windows `.exe` is built per-machine via the included
  PyInstaller script/workflow (no Windows builder in the dev environment);
  SeaArt + PixAI adapters are marked *experimental* in the GUI (their internal
  APIs shift often — they degrade gracefully and never take the app down).
