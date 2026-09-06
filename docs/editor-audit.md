# Editor upgrade — audit & reference study (E1)

Scope: the "AI Filmmaking Studio + professional video editor" spec. This doc records
(a) what PF2 already has vs. what the spec adds, and (b) what was learned from the ten
reference repositories, with licenses checked before any reuse.

## What already exists (kept, not rebuilt)

Film Studio S1–S6 already covers: project→scene→shot→take single source of truth,
Director proposals (accept/reject/edit — never silently applied), asset bibles with
copy-on-write versions + pinning + affected-shot propagation, continuity engine +
review, per-shot takes with compare/select/import, first/last-frame chaining, cost
estimation + budget modes enforced before spend, QA (ffprobe + black/freeze
heuristics) + repair queue, storyboard grid/contact-sheet/inspector with original SVG
shot diagrams, camera/lighting visual controls, timing panel (gaps vs transitions),
audio tracks + subtitles + burn-in, ffmpeg export (conform → concat/xfade → amix)
with post-render review, footage corpus (uploads + stock adapters + licenses stored
verbatim), deterministic mock generation (FakeProvider), checkpointed jobs surviving
restart, Docker.

## What the spec genuinely adds (built in phases E2–E8)

1. An explicit editable **sequence** (multi-track timeline) distinct from the
   storyboard-derived timing: tables `film_timeline_tracks`, `film_timeline_clips`,
   `film_markers`, `film_revisions` (all additive, D61-migrated).
2. `film/sequence.py`: build-from-storyboard, clip CRUD/move/trim/split/ripple,
   validation, markers, bounded snapshot undo/redo that survives reloads.
3. Clip-aware export: when a sequence exists it — not the storyboard — drives the
   render, honouring per-clip trim/speed/effects/fades/volume. Positions are literal
   so export always matches preview timing; dissolves hold the outgoing clip's last
   frame and cross-fade in place (no handle media needed, no timing shift).
4. A professional editor UI at `/film/editor`: media bin | preview | inspector over a
   multi-track timeline with drag/trim/split/ripple/marquee/snapping(+toggle)/zoom/
   markers/track mute-solo-lock, frame stepping, shortcuts, undo/redo, autosave.
5. Generation review queue (approve/reject/regenerate/compare on takes), batch
   generation with cost preview, storyboard↔timeline selection sync, [Build
   Timeline] and clip↔take replacement.

## Reference repositories — licenses first

| Repo | License | Use |
|---|---|---|
| cutaway | MIT | Patterns + limited code reuse permitted (attribution kept) |
| OpenCut (rewrite) | MIT | Timeline is a stub in the current repo — architecture notes only |
| BlueFish | Apache-2.0 | Patterns (JSX, would need porting anyway); attribution if ported |
| storyboard-gen | MIT | Patterns + reuse permitted |
| seq | **No LICENSE file** (README claims MIT, file absent) | Patterns only — no code copied |
| storyboard-tool | No license | Patterns only |
| story2video | No license | Patterns only |
| ai-video-production-editor | GPL-3.0 | Patterns only (copyleft incompatible) |
| storyboard-forge | AGPL-3.0 | Patterns only (network copyleft — hazardous for a hosted app) |
| livepeer/storyboard | — | Not publicly reachable (private/removed); not studied |

No code was copied from any repo. All timeline/editor code in PF2 is written natively
for this codebase; where a *design idea* below came from a specific repo it is noted.

## Patterns adopted (and their origin)

- **Literal clip positions, pure engine helpers, flat clip storage** (cutaway):
  clips are rows keyed by track_id, not nested arrays; geometry/hit-test/snap math
  lives in pure exported functions so it is unit-testable and a canvas rewrite stays
  contained. Half-open ranges `[start, end)` for adjacency.
- **Snapshot undo with gesture coalescing** (cutaway): full-state snapshots, not
  inverse commands; a drag gesture lands as ONE history entry. PF2 keeps history
  server-side (`film_revisions`, two bounded stacks) so undo survives reloads; the
  client applies edits optimistically and commits a gesture as one `batch` call.
- **Derived playback clock** (cutaway): the playhead is derived from a clock origin
  (`origin + (now - startedAt)`), never accumulated per-frame, so seeks don't drift
  and background tabs stay in sync; React state updates are throttled (~30 Hz) while
  a ref advances every frame (seq).
- **Snap both edges, pick the closer; break-out threshold** (cutaway + seq): snap
  candidate list = clip edges ∪ playhead ∪ markers ∪ 0; threshold in px ÷ pxPerSec;
  once snapped, a small extra drag distance is needed to break away.
- **DOM clips + canvas ruler** (seq): Tailwind-styled clip divs (thumbnails, labels)
  with a canvas ruler whose tick interval comes from a discrete zoom ladder.
- **Shortcut registry** (BlueFish): one `action → {keys, description}` map drives
  both the key handler and the shortcuts help/tooltips, with a text-input guard.
- **Narrow LLM contract, wide runtime record** (ai-video-production-editor, design
  only): AI storyboard/shot generation asks the model for a small validated schema;
  everything runtime (takes, review state, timing) is app-owned columns.
- **Feedback → change-request → per-shot task** shape for the review queue
  (ai-video-production-editor, design only), mapped onto takes + shot repair.
- **Derived timeline / board-timeline single source** (storyboard-tool): board and
  editor never store two copies of shot timing — the sequence is built FROM the
  storyboard explicitly, and links (`clip.shot_id`) keep selection sync + replace
  flows honest.
- **Clamp-with-warning** (storyboard-tool): duration clamps report what was clamped
  instead of failing silently.
- **Controlled camera vocabulary expanded server-side** (storyboard-gen): already
  PF2's approach (presets → prose in `build_prompt`); kept.

## Rejected approaches (and why)

- Canvas-rendered timeline (cutaway): PF2 timelines are hundreds of clips at most,
  DOM + viewport culling is sufficient, and DOM keeps Tailwind tokens/accessibility.
  Hit-testing still lives in pure helpers so the swap stays possible.
- Client-only undo (seq): loses history on reload and can desync from the server;
  PF2 stores snapshots server-side.
- Deep-clone command classes (BlueFish): command boilerplate with snapshot cost;
  plain snapshots are simpler and equally correct at this scale.
- Seek-per-frame video decoding for preview (BlueFish): unusable at real-time rates;
  PF2 previews via `<video>` element src-swap + threshold seeks.
- xfade that shortens the timeline (classic NLE overlap): would make export timing
  differ from the editor; PF2 holds the last frame and cross-fades in place.
