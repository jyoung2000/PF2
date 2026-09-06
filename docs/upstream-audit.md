# Upstream repository audit (Phase 2)

Phase 1 built PromptForge's Forge layer as provider-neutral equivalents because
this environment could not reach GitHub. **In this session the repositories are
reachable**, so all 15 were cloned (`--depth 1`) and read. This document records
what was actually inspected, how it compares to PromptForge, and the decision.

Method: `git clone` each repo, read the files listed, diff the concepts against
the existing implementation, then adopt / keep / ignore per feature.

## Licences

| Repo | Licence | Obligation |
| --- | --- | --- |
| Open-Generative-AI, Open-AI-Design-Agent, Vibe-Workflow, Generative-Media-Skills, Seedance-2.5-API, Image-Enhancement-API, Video-Utilities-API, Speech-to-Text-API, Text-to-Speech-API, AI-3D-Model-API, free-claude-ai-image-generator, awesome-ai-image-models | MIT | Attribution if source is copied |
| awesome-ai-video-models | no LICENSE file at HEAD | Treated as reference documentation only — facts used, no text copied |
| AI-Youtube-Shorts-Generator | no LICENSE file at HEAD | Treated as reference documentation only — algorithm concept used, no code copied |

**No upstream source file was copied into PromptForge.** Endpoint names,
parameter names and published capability facts are interface/API facts, used to
write our own adapters against the same HTTP APIs. Where catalogue *facts*
(price, resolution, notes) informed catalogue entries, the entry records
`source_urls` + `evidence` + `confidence` so the provenance is visible in-app.

## The central finding

Five of the "API" repos (Image-Enhancement, Video-Utilities, Speech-to-Text,
Text-to-Speech, AI-3D-Model) plus Seedance-2.5-API are **thin clients over one
service: MuAPI** — identical base URL `https://api.muapi.ai/api/v1`, identical
`x-api-key` header, identical submit → poll `predictions/{id}/result` contract
(verified in each repo's `examples/quickstart.py` and in
`Seedance-2.5-API/seedance_api.py:511-534`).

That contract is the same shape as PromptForge's existing
`GenerationProvider.submit()/poll()`. So the correct integration is **one new
adapter** (`generation/muapi.py`) plus catalogue `modes` declarations — not six
integrations, and emphatically not a hard dependency: MuAPI sits in the provider
registry beside fal/Replicate/WaveSpeed and everything degrades honestly when it
is absent.

## Feature-by-feature

| Repository | Upstream files inspected | Feature | PromptForge equivalent | Gap | Decision | Implementation | Verified |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Image-Enhancement-API | `README.md` (model table), `examples/quickstart.py`, `.env.example` | Upscale (`ai-image-upscaler`, `seedvr2-image-upscale`, `topaz-image-upscale`), background removal (`ai-background-remover`) | `upscale_image` / `remove_background` tools existed but no provider declared them → honest-unsupported | Real execution missing | **ADD** | `generation/muapi.py` + `pricing.json` modes | mocked-transport tests |
| Video-Utilities-API | `README.md`, `examples/quickstart.py` | Video upscale (`ai-video-upscaler`, `topaz-video-upscale`), video→audio (`mmaudio-v2-video-to-video`), text→audio (`mmaudio-v2-text-to-audio`) | `video_to_audio` honest-unsupported; no video upscale tool | Missing | **ADD** | same adapter; new `upscale_video` tool | tests |
| Speech-to-Text-API | `README.md`, `examples/quickstart.py` | `openai-whisper` (audio_url/language/response_format), `gemini-audio-vision` (audio Q&A) | `transcribe_audio` honest-unsupported | Missing | **ADD** | same adapter; `gemini-audio-vision` also wired as the **audio evaluator** | tests |
| Text-to-Speech-API | `README.md`, `examples/quickstart.py` | `minimax-speech-2.6-hd/turbo`, `elevenlabs-tts-turbo-2-5`, `elevenlabs-text-to-dialogue-v3`, `gemini-*-tts`; voice_id/speed/emotion params | `generate_speech` honest-unsupported | Missing | **ADD** | same adapter; params from the schema DB | tests |
| AI-3D-Model-API | `README.md`, `examples/quickstart.py` | `tripo3d-h31-text-to-3d`, `meshy-6-image-to-3d`; `.glb` output | `generate_3d` honest-unsupported | Missing | **ADD** | same adapter + artifact landing for non-media outputs | tests |
| Seedance-2.5-API | `mcp_server.py` (197 ln), `seedance_api.py` (endpoint set, `wait_for_completion`), `CHARACTER_CONSISTENCY.md` | Typed MCP tools; endpoint slugs as first-class args; multi-reference lists (`images_list`/`videos_list`/`audios_list`); `last_image`; `generate_audio` | Our tools are typed and capability-gated already; Seedance existed as a fal/wavespeed family | Endpoint-slug passthrough + multi-ref | **ADAPT** | MuAPI adapter accepts explicit endpoint slugs; kept our typed-tool contract (stronger: validation + job rows + cost) | tests |
| Generative-Media-Skills | `schema_data.json` (267 endpoints), `core/media/*.sh`, `core/platform/check-result.sh`, `library/**/SKILL.md` | Per-endpoint JSON input schemas; capability categories; skill boundaries; CLI/JSON contracts | Our `models_catalog.json` + `forge/tools.py` typed validation | Upstream has real per-endpoint parameter schemas we lacked | **ADAPT** | derived a compact endpoint→parameter map for the MuAPI adapter; kept our tool layer (typed, queued, costed) | tests |
| Generative-Media-Skills | `schema_data.json` → `openrouter-vision` (`images_list`,`prompt`,`system_prompt`,`model`) | A real vision endpoint | Evaluation was metadata-only | **The** evaluation gap | **ADD** | `forge/vision.py` — vision backends: Anthropic, OpenAI-compatible, MuAPI `openrouter-vision` | tests |
| Vibe-Workflow | `packages/workflow-builder/src/components/utility.jsx` (node defs, `outputs:[{type:"text"\|"image_url"\|"video_url"}]`), `NodeFlow.jsx`, `WorkflowStore.jsx`, `client/app/workflow/[id]/page.js` | **Typed node ports** and connection typing | Our graph validated ids/edges/cycles but ports were untyped | Type-checking of connections | **ADAPT** | typed ports + edge type validation in `forge/workflows.py` | tests |
| Open-AI-Design-Agent | `packages/design-agent/**`, `server/app/**`, `client/**` | Asset planning, dependency order, reference inheritance, regeneration | `forge/planner.py` (presets, deps, locks, fork, rerun-failed) | Ours already covers these; upstream is Next/Python split | **KEEP ours** | — | existing tests |
| Open-Generative-AI | `app/**`, `components/**`, `Dockerfile`, `docker-compose.yml`, `package.json` | Generation workspace UI, history, provider connection, local inference | Gallery + Forge + Settings | Ours is broader (library, scrapers, film) | **KEEP ours**; borrowed nothing visual | — | — |
| awesome-ai-image-models | `README.md` (2026 model tables incl. GPT Image 2, Nano Banana Pro, Seedream 5.0 Pro, Imagen 4 Ultra, Ideogram Character, Z-Image Turbo) | Current model facts: maker, APIs, price/image, notes | Seed catalogue predated these | Catalogue staleness | **ADAPT** (as *reference*, not truth) | new catalogue entries with `source_urls`/`evidence`/`confidence` | catalogue tests |
| awesome-ai-video-models | `README.md` (Seedance 2.5, Veo 3.1, Sora 2 + **API sunset 2026-09-24**, Kling v3.0, Runway Gen-4.5, PixVerse V6, Vidu Q3 Pro, Hailuo 2.3) | Price/sec, max res/length, audio, references | Same | Same | **ADAPT** | same, incl. a `deprecation` field for Sora 2 | catalogue tests |
| AI-Youtube-Shorts-Generator | `shorts_generator/highlights.py`, `clipper.py`, `pipeline.py`, `transcriber.py` | Transcript → LLM highlight ranking (`score`,`hook_sentence`,`virality_reason`) → **overlap suppression** → 9:16 crop | `clip_video` node cut at scene changes only | No ranking/dedupe/reframe | **ADAPT** (concept) | `forge/highlights.py` — deterministic ranking + overlap suppression, optional LLM, 9:16 reframe in `clip_video` | tests |
| free-claude-ai-image-generator | `README.md`, `examples/**` | MCP-style tool invocation for image gen, credential handling | `/api/forge/tools` typed layer | Ours equivalent; no MCP server surface | **ADD** small | documented MCP mapping in `docs/integration-ideas.md`; tool descriptors already MCP-shaped | — |
| awesome-generative-ai-apps | `README.md` | Discovery list | — | — | **IGNORE** (no unrelated app imports) | — | — |

## Deliberately not adopted

- Upstream Next.js/Express app skeletons — PromptForge is a single FastAPI +
  Vite container; adopting them would fork the architecture for no user gain.
- Upstream workflow *UI* — ours is integrated with our own token system and
  already renders availability/approval state.
- Any per-provider SDK dependency — the existing adapters use `httpx` directly
  and stay uniform.
