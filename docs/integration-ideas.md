# Integration ideas registry (spec §16, §21)

The one-shot spec names 15 reference projects. This environment cannot fetch
them (egress policy) and the spec prefers reimplementing interfaces over
copying source, so each row records the *requirement* extracted from the
project's stated purpose and where PromptForge implements the equivalent —
provider-neutral, against our own contracts. No external code was copied;
no license obligations attach (§21). Rows marked *candidate* are future work.

| Reference project | Capability taken as requirement | Where it lives in PromptForge | Difficulty | Status |
| --- | --- | --- | --- | --- |
| awesome-ai-image-models | structured image-model metadata | `models_catalog.json` + `forge/catalog.py` registry | low | done |
| awesome-ai-video-models | structured video-model metadata | same registry, `modality: video` entries | low | done |
| Generative-Media-Skills | agent-native typed media tools | `forge/tools.py` (typed JSON in/out, job ids, capability-validated) | medium | done |
| Open-AI-Design-Agent | multi-asset creative planning | `forge/planner.py` Creative Plans | medium | done |
| Vibe-Workflow | node-based media workflows | `forge/workflows.py` + Workflows UI | high | done |
| Open-Generative-AI | generation-workspace UI patterns (job cards, model switcher, parameter-aware forms) | Forge Compose/Lab pages | medium | done |
| Image-Enhancement-API | upscale / background removal ops | catalog-declared `upscale`/`remove_background` modes via existing adapters; unsupported until an offer declares them | low | done (honest-unsupported) |
| Video-Utilities-API | video enhance/extend/clip utilities | ffmpeg local ops (film/graphics, film/footage) + `ai_clip_video` workflow node | medium | partial (local ops) |
| Speech-to-Text-API | transcription op | `transcribe_audio` tool → catalog mode `transcription` | low | done (honest-unsupported until declared) |
| Text-to-Speech-API | narration/speech op | `generate_speech` tool → catalog mode `tts` | low | done (honest-unsupported until declared) |
| AI-3D-Model-API | text/image → 3D op | `generate_3d` tool → catalog mode `text_to_3d` | low | done (honest-unsupported until declared) |
| Seedance-2.5-API | Seedance as a provider offer | already a family in `pricing.json` (fal/wavespeed offers) — an adapter row, not an app | — | done previously |
| free-claude-ai-image-generator | free-first provider posture | routing policy step 2 (prefer configured free/local), provider settings badges | low | done |
| awesome-generative-ai-apps | discovery source for future features | this registry | — | ongoing |
| AI-Youtube-Shorts-Generator | long video → clips workflow | `shorts_pipeline` workflow template (transcribe → highlights → clip → captions → export); transcription step reports unsupported until a provider declares it | medium | template shipped |

License audit note: PromptForge's own license is unchanged. Nothing in this
work vendors third-party source; dependencies added (if any) are recorded in
package manifests with their licenses.
