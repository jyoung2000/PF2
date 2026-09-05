# PromptForge GUI mock (Claude Design canvas)

The editable mock of every PromptForge screen lives in a Claude Design canvas:
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
