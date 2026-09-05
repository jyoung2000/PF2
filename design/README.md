# PromptForge GUI: a browsable copy and an editable mock

Two views of the same GUI live here.

**Browsable copy** — `preview/index.html`, captured from the running container app (see below).

**Editable mock** — a Claude Design canvas you can restyle by hand:
**https://claude.ai/code/artifact/2922255e-0f30-4de5-a1bc-58f9968a4159**

Everything on it is generated from this directory, and every value in here is
lifted from the real frontend — `frontend/tailwind.config.ts` (colors, radii,
fonts) and `frontend/src/styles.css` (`.btn` `.chip` `.card` `.input` `.label`)
plus the component markup — so the mock is what the container renders.

| File | What it is |
| --- | --- |
| `lib.mjs` | tokens, atoms (buttons, chips, inputs, badges, status dots), app chrome, placeholder art, the document wrapper with the tweak chips |
| `screens_*.mjs` | one module per screen family (gallery / detail / phone, collections / models / inspiration, film storyboard, studio / settings, token sheet) |
| `gen.mjs` | writes the `*.dc.html` artboards and `canvas.json` |
| `*.dc.html`, `canvas.json` | the generated artboards — the last state synced with the canvas |
| `capture.sh`, `capture.mjs`, `preview_seed.py` | the browsable copy: seed a demo library, run the app, snapshot every screen |
| `preview/` | the captured pages — open `preview/index.html` |

## Browsable copy of the container GUI (`preview/`)

`design/preview/index.html` is a static copy of the GUI **captured from the
running app**, not a redrawing. `design/capture.sh` builds the frontend, seeds a
throwaway demo library, serves it with the real FastAPI app on port 5643, and
saves each route's rendered markup together with the app's own stylesheet, fonts
and media. Open `design/preview/index.html` in a browser after cloning; the
navigation links point at the sibling captures, so it browses like the app.

```bash
bash design/capture.sh            # regenerate every screen
```

Twenty-four screens are captured: the gallery (grid, search, post drawer),
collections, models, the six Inspiration tabs, the six Film Studio tabs, the
three Studio tabs, settings, and two phone-width views.

What it is and is not:

- **Real markup.** Every element, class and value comes from the app. If the
  GUI changes, re-run the script and the copy changes with it.
- **Static.** The module script is dropped, so controls do not respond and
  nothing calls an API. Form state is serialized as attributes, so selects and
  inputs show what the live app showed.
- **Sample data.** Placeholder artwork, invented prompts, creators and a demo
  film project, all from `design/preview_seed.py`. No credential is written, so
  Settings captures in its unconfigured state — what a fresh container shows.

## Editing loop (mock → container)

1. Restyle on the canvas: the tweak chips above each screen (accent, ink, panel,
   well, line, fg, mute, faint, card radius, element radius, display font) or
   any element through the properties panel. Save.
2. Tell Claude what changed (or which screen to sync). Claude reads the saved
   canvas, diffs it against the artboards here, and applies the change to the
   code: tweak values go to `tailwind.config.ts` / `styles.css`, per-element
   changes go to the React components. It rebuilds, runs the tests, commits.
3. Update the container on Unraid (pull, `docker compose build`, `up -d`).

Tweak → code mapping:

| Tweak chip | Code |
| --- | --- |
| accent | `colors.ember` (`ember-soft` = accent lightened 20 %) |
| ink · panel · well · line | `colors.ink` / `panel` / `well` / `line` |
| fg · mute · faint | `colors.fg` / `mute` / `faint` |
| card radius | `borderRadius.card` (used by `.card`) |
| element radius | `borderRadius.el` (buttons, inputs, thumbnails); chip radius = 60 % of it |
| display font | `fontFamily.display` + the `@fontsource` import in `styles.css` |

## Regenerating the canvas (code → mock)

After a GUI change in `frontend/`, update the matching screen module here and:

```bash
cd design && node gen.mjs
```

Then seed and save the canvas with the Claude Design skill (`/design`), passing
every `*.dc.html` plus `canvas.json` and the existing artifact URL so the link
stays the same. The seeded page (`promptforge-gui.html`) and any screenshots are
build outputs — do not commit them.
