# Integration ideas registry

Phase 1 wrote this from the reference projects' stated purposes (GitHub was
unreachable). **Phase 2 replaced it with what the source actually says** — see
`docs/upstream-audit.md` for the files read and the per-feature decisions.

## Adopted in Phase 2

| From | What was adopted | Where | Why ours changed |
| --- | --- | --- | --- |
| Image-Enhancement / Video-Utilities / Speech-to-Text / Text-to-Speech / AI-3D-Model / Seedance-2.5 APIs | One shared HTTP contract (`POST /{endpoint}` → id, `GET /predictions/{id}/result`, `x-api-key`) and the endpoint + parameter names | `generation/muapi.py`, `pricing.json` capability families | Six "honest placeholder" tools became real execution through one adapter |
| Generative-Media-Skills | `schema_data.json`'s per-endpoint parameter schemas; the discovery that `openrouter-vision` exists | `generation/muapi.py` field map; `forge/vision.py` | Gave us real parameter names, and the vision backend that made evaluation genuine |
| Speech-to-Text-API | `gemini-audio-vision` (listen-and-answer) and `openai-whisper` | `forge/evaluate.py::_evaluate_audio` | Audio results are transcribed and compared, not assumed |
| Vibe-Workflow | Typed node ports (`text` / `image_url` / `video_url` outputs) | `forge/workflows.py` `PORT_TYPES`, edge type-checking, `/api/forge/workflow-node-types` | Bad connections are caught in the editor instead of mid-run |
| AI-Youtube-Shorts-Generator | Rank-then-suppress-overlaps highlight selection, 9:16 reframing | `forge/highlights.py`, `clip_video` node | Three clips are three different moments, and shorts come out shorts-shaped |
| awesome-ai-image-models / awesome-ai-video-models | Current model facts (price, resolution, duration, capabilities, an API sunset date) | `models_catalog.json` entries with `source_urls` / `evidence` / `confidence` | Catalogue gained 11 current models and every entry now carries provenance |
| Seedance-2.5-API | Endpoint-slug-as-argument, multi-reference lists, MCP tool shape | MuAPI adapter accepts explicit slugs; tool descriptors stay MCP-shaped | Seedance is an offer on an existing family, not a special case |

## Deliberately kept as-is

- **Plans** vs Open-AI-Design-Agent — ours already does asset decomposition,
  dependency ordering, reference inheritance, per-asset regeneration, locking
  and forking, inside one service.
- **Workspace UI** vs Open-Generative-AI — ours is integrated with the wider
  library/scrapers/film app; only the typed-port idea was worth importing.
- **awesome-generative-ai-apps** — a discovery list; nothing imported.

## Still open (not implemented, not pretended)

- An MCP *server* surface: the tool descriptors are MCP-shaped
  (`name`/`description`/typed input/typed output) and `/api/forge/tools`
  exposes them, but PromptForge does not yet speak the MCP wire protocol.
- Talking-head, lip-sync and masked inpainting: no catalogue offer declares
  them, so they remain honestly unsupported.
- Local inference adapters (Ollama-style for images/video).
