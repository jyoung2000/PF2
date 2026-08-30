---
kind: foundation
version: 1
updated: 2026-08-30
scope: fundamentals inherited by every model knowledge file
---

# Prompting foundation

The shared craft underneath every image/video model. Model files build on this;
when a model file contradicts this, the model file wins.

## Prompt anatomy

A reliable prompt answers, in rough order: **subject → action/pose → setting →
composition/camera → lighting → palette/mood → style/medium → quality & technical
modifiers → (video) motion & audio**. Not every slot every time — but missing
slots are where models improvise, and improvisation is where money gets wasted.

- **Subject first.** Models weight early tokens most. Lead with the thing that
  must be right; bury negotiables at the end.
- **One idea per clause.** Comma-separated clauses beat run-on sentences for
  tag-style models; clean short sentences beat both for natural-language models.
- **Concrete > abstract.** "weathered brass diving helmet, verdigris" beats
  "old-looking metal headgear". Name materials, textures, era, brands of light.
- **Counts and relations need scaffolding.** "two women, the left one holding
  the map" fails more than "two women study a map; the taller one points at it".
- **Don't stack synonyms** ("beautiful, gorgeous, stunning") — they dilute
  attention. Spend tokens on information, not enthusiasm.
- **Length sweet spots differ by model** (see each model file). Universal shape:
  short prompt → model's house style; long prompt → your style. Both are valid
  tools; know which one you're using.

## Shot types & framing (image and video)

extreme wide / establishing · wide (full body + environment) · medium-wide
(knees up) · medium (waist up) · medium close-up (chest up) · close-up (face) ·
extreme close-up (eyes, texture) · insert/detail shot · two-shot · over-the-
shoulder · POV · top-down flat lay · profile · back view.

Naming a shot type is the single cheapest control for composition. Pair it with
lens language for realism: "85mm portrait, f/1.8" (compressed, creamy bokeh),
"24mm wide, deep focus", "100mm macro", "8mm fisheye", "anamorphic 2.39:1
with oval bokeh and horizontal flare".

## Camera angles

eye level (neutral) · low angle (power, scale) · high angle (vulnerability,
maps) · Dutch/canted (unease) · bird's-eye / drone top-down · worm's-eye ·
shoulder level for conversational realism. Angle + shot type + lens is the
compositional tripod: set all three when the framing matters.

## Camera movements (video)

static/locked · pan · tilt · dolly in/out (physical move — feels weighty) ·
zoom in/out (optical — feels observational) · dolly zoom (vertigo) · truck
left/right · pedestal up/down · crane/jib · orbit/arc · tracking/follow ·
handheld sway (documentary energy) · steadicam glide · whip pan (transition) ·
FPV dive (drone through spaces) · roll · rack focus (attention hand-off) ·
snorricam (subject locked, world moves).

Video prompting rules of thumb: **one primary camera move per shot**; describe
it early ("slow dolly-in on…"); give it a speed adverb (slow/steady/rapid);
motion verbs for the subject separate from the camera clause. Stacked moves
("orbit while zooming during a whip pan") produce mush on every current model.

## Composition

rule of thirds · centered/symmetrical (formal, imposing) · golden ratio ·
leading lines · frame-within-frame (doorways, mirrors) · foreground occlusion
for depth (something soft in front) · negative space (isolation, product shots)
· silhouette · reflection · pattern-and-break · headroom/lead room for moving
subjects. Depth recipe that almost always helps: **foreground element + subject
+ atmospheric background**.

## Lighting

Direction: front (flat) · side (texture, drama) · back/rim (separation, halos)
· top (interrogation) · under (horror). Quality: hard (crisp shadows, noir) vs
soft (wrapped, beauty). Named looks that models know well: golden hour ·
blue hour · overcast softbox sky · window light · candlelight · neon signage ·
sodium-vapor streetlight · moonlight · firelight · studio three-point ·
Rembrandt (triangle cheek) · butterfly · split light · chiaroscuro · god rays /
volumetric shafts · caustics (water/glass) · bioluminescence · practicals in
frame (lamps, screens). Specify **source, direction, and quality**; add color
temperature words (warm tungsten, cool daylight, mixed) for grade control.

## Color & grade

Palettes: monochrome · analogous (calm) · complementary (punch: teal-orange,
red-cyan) · pastel · saturated pop · muted/desaturated · earth tones · jewel
tones · duotone. Film/grade vocabulary: Kodak Portra warmth · Ektachrome ·
CineStill 800T halation · bleach bypass · cross-processed · faded matte blacks
· crushed shadows · HDR (use sparingly) · film grain · 35mm/16mm texture.
State palette as a constraint ("palette limited to rust, cream, and deep
teal") — constraint phrasing outperforms adjective phrasing.

## Style & medium

photography (name the genre: editorial, documentary, product, street) ·
cinematic still ("film still from…") · oil/watercolor/gouache/ink · pixel art ·
low-poly · isometric 3D · claymation · papercraft · risograph · screenprint ·
blueprint · ukiyo-e · art nouveau · brutalist · y2k chrome · vaporwave ·
cyberpunk · solarpunk · dieselpunk · cottagecore. Anchoring era + medium +
three descriptors beats naming living artists (many models suppress or distort
artist names anyway; movements and mediums transfer better).

## Motion & pacing (video)

Describe, in order: camera move · subject motion · secondary motion (hair,
cloth, dust, rain) · speed (slow motion 120fps, real-time, timelapse,
hyperlapse) · loop intent if needed ("seamless loop"). Secondary motion is the
difference between "animated photo" and "footage" — always give the scene one
ambient system: drifting particles, flickering light, wind in fabric, steam.
For pacing: one beat per 4–6s clip ("she turns, then smiles" is two clips).
Transitions worth naming: match cut, whip-pan transition, morph, speed ramp.

## Sound & audio cues (audio-capable video models)

Layer it like a mix: **ambience** (room tone, rain, crowd) · **diegetic
effects** synced to visible actions (footsteps, door, pour) · **dialogue** in
quotes with delivery notes ("whispered, tired: 'we're late'") · **music** as
genre + mood + instrumentation ("sparse piano, distant strings, melancholy").
Say what should NOT sound too ("no music, only room tone"). Sync language:
"the thud lands exactly as the case hits the table."

## Consistency: characters, styles, series

- **Seeds**: same seed + same prompt + small edits = controlled variation;
  log seeds for anything you may want to revisit (PromptForge stores them).
- **Style references** (`--sref`-style codes, style ref images): lock a look
  across a series; keep subject prompts clean and let the ref carry style.
- **Character references** (face/character ref images, `--cref`-style):
  reuse one clean, front-lit, neutral-background portrait; describe wardrobe
  in text (refs carry face better than clothes).
- **LoRAs**: the strongest identity/style lock where supported; state trigger
  words exactly, keep weights 0.6–0.9, at most 2–3 LoRAs before quality drops.
- **Text recipe for consistency without refs**: give the character a compact
  "passport" — name, age, 3 physical anchors, 2 wardrobe anchors — and paste it
  verbatim into every prompt of the series.
- **Environment continuity**: reuse the exact location sentence; change only
  the action clause between shots.

## Negative prompting

Where supported, negatives are for *recurring* failures, not incantations.
Useful core: worst quality, lowres, jpeg artifacts, watermark, text, extra
fingers/limbs, deformed hands, cross-eye. Keep negatives short — huge negative
walls fight the positive prompt. Diffusion-style models respect them; LLM-based
natural-language models (Flux-class, most video models) largely ignore negative
fields: phrase exclusions positively instead ("empty street" not "no people").

## Cinematic quality heuristics

1. Motivate the light (visible or implied source) — instant realism.
2. One subject, one story per frame; if the eye wanders, cut scope.
3. Atmosphere (haze, dust, rain, steam) sells volumetric light and depth.
4. Imperfection reads as truth: grain, slight motion blur, worn surfaces,
   asymmetry. "Flawless" reads as AI.
5. Color scripts: two dominant hues + one accent. More = commercial mush.
6. For video, end the prompt with the frame you want to *hold* — models
   resolve toward their final clause.
7. Wardrobe/props anchor era faster than any style tag.
8. If a render is 90% right, iterate with the same seed and edit one clause —
   don't reroll from scratch.
9. Aspect ratio is content: 2.39:1 implies cinema, 9:16 implies phone
   intimacy, 1:1 implies product/portrait formality.
10. Say the medium even for photos ("35mm film still") — it sets texture,
    contrast, and lens behavior in one token.

## Failure patterns to route around

hands & fingers (hide, glove, or crop; or negative-prompt) · text/lettering
(most models garble; keep signage abstract or add real text in post) · counts
above 3 · faces at extreme wide (add a close-up pass) · physics in long video
clips (keep clips ≤6s) · two named characters interacting (strongest models
only, or shot/reverse-shot as separate generations) · mirrors and reflections
(gorgeous when they work, verify them) · overlapping limbs in group shots.
