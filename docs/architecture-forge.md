# Forge: model-aware prompt engineering layer — architecture note

*(spec §1 deliverable — existing architecture, new architecture, boundaries,
migration, flags, fallback. Kept short; decisions live in CLAUDE.md.)*

## Existing architecture (preserved, unchanged)

FastAPI + sync SQLAlchemy/SQLite (WAL) monolith on port 5643; React/Vite SPA
served as static files. Relevant to this work:

- **Providers** — `generation/base.py` adapter contract (submit/poll,
  test-connection that never charges), one file per provider (fal, Replicate,
  WaveSpeed), keys in the settings table (write-only, masked).
- **Catalog** — `pricing.json` seeded → DATA_DIR copy wins (D16); per
  family × provider: model id, prices, declared `modes` with provider input
  field names (D76).
- **Routing** — `generation/router.py` (cheapest connected, D29) and
  `film/scoring.py` (weighted, explainable, history-aware ranking, film-only).
- **Jobs** — `generations` table + in-process queue worker (D14): statuses
  queued|running|succeeded|failed, cost estimate, outputs ingested as Posts.
- **Prompt tooling** — Studio templates (learned from collections), Enhance
  (budget-gated LLM, D12/D41), knowledge files per model family (D11).
- **Model knowledge** — `models_meta` (library-observed), `aliases.py`
  (normalization), `DATA_DIR/knowledge/models/*.md`.
- **Migrations** — `db.migrate_schema()` additive on boot (D61).

## New architecture: the `forge` package

`backend/promptforge/forge/` + `api/forge.py`, mounted under `/api/forge/*`.
Frontend gains one section (`/forge/*`). Nothing existing is moved.

| Module | Role | Spec |
| --- | --- | --- |
| `catalog.py` | Model Intelligence Registry: `models_catalog.json` (seeded → DATA_DIR copy, additive-merged like pricing) normalized per family; merged live with pricing offers, connection state, library observations (`models_meta`) and knowledge files. CapabilityResolver + ParameterValidator + cost via `generation/pricing`. | §2 |
| `intent.py` | Deterministic intent extraction from a brief (modality, duration, aspect ratio, style, consistency, references, budget) with evidence per field. | §3 |
| `router.py` | General router: catalog offers × intent constraints → ranked, explainable candidates (task/capability fit, quality prior, history from `generations`, cost, latency, free/local preference, user prefs). Every pick overridable. | §3 |
| `compiler.py` | Prompt Compiler: idea → intent → structure → model-specific optimization (catalog prompt recommendations + knowledge stats; optional LLM polish) → parameters → checks → PromptPackage. Recompile on model switch keeps intent. | §4 |
| `tools.py` | Typed, provider-neutral tool layer (generate_image, image_to_video, …) validating capability + params, then riding the existing generation queue; structured job ids/status; MCP-compatible shape without requiring MCP. | §7, §11 |
| `experiments.py` | Test Lab: experiments → prompt variants (versioned, forkable) → runs (generation snapshot, score, cost, latency). | §5 |
| `evaluate.py` | Deterministic result checks (aspect/duration/type/omissions/over-constraint) + optional LLM critique → findings + a proposed revision as a NEW version with a visible diff. | §6 |
| `planner.py` | Creative Plans: multi-asset plans (deterministic presets, optional LLM draft) with per-asset prompt package, dependencies, lock/regenerate/fork. | §8 |
| `workflows.py` | Serialized node-graph workflows (JSON), validation, topological execution through the tool layer; templates incl. the shorts pipeline. | §9, §17 |
| `usage.py` | Usage/cost aggregation over `generations` (+ runs): per model/provider success, latency, spend, fallbacks. | §13 |

## Integration boundaries

- Forge **calls into** the generation queue/adapters and pricing; it never
  bypasses them. New capabilities (TTS/STT/upscale/3D…) become catalog-declared
  modes served by the same adapters; a mode nobody declares stays honestly
  unsupported (mirrors D76).
- Forge **reads** knowledge files/stats; writes stay with the knowledge engine.
- The LLM is optional everywhere: every Forge feature has a deterministic path
  and reports when an LLM would improve output but is not configured (D41
  pattern). Prompt authoring, model intelligence and testing work with zero
  providers configured.
- Film Studio is untouched; its scoring stays film-scoped. Shared idea
  (ranked, explainable offers) is generalized in `forge/router.py`, not moved.

## Migration strategy

New tables only (`prompt_experiments`, `prompt_variants`, `variant_runs`,
`creative_plans`, `plan_assets`, `workflows`, `workflow_runs`), registered on
the shared Base and covered by `create_all` + `migrate_schema()` (D61). No
existing table changes shape; no data migration. `models_catalog.json` follows
the pricing.json lifecycle (seed copied on first boot, user copy wins,
additive merge for new seed fields).

## Feature flags & fallback behavior

- Everything ships enabled; features degrade, never error, when unconfigured:
  no generation provider → compile/test-lab/plan/workflow authoring all work,
  execution reports what to connect; no LLM → deterministic paths.
- Provider fallback is **opt-in** (`forge_allow_fallback`, default off): a
  failed job may be retried once on the next-ranked eligible offer as a NEW
  generation row linked to the failed one — the switch is always visible
  (status, event log), never silent (§12.5).
- Routing policy order (§12): explicit user choice → configured free/local
  capable of the task → best configured offer → opt-in fallback.

## Reference projects (§21, §15–16)

The 15 reference repositories are treated as requirement sources, not code
sources: this environment's egress policy blocks fetching them, and the spec
prefers provider-neutral reimplementation. Every capability was implemented
from the requirement against PromptForge's own contracts; no external code was
copied, so no license obligations attach. `docs/integration-ideas.md` tracks
the mapping and future integration candidates.
