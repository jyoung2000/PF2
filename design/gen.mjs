import { writeFileSync } from 'node:fs'
import { galleryDoc, mobileDoc, detailDoc } from './screens_gallery.mjs'
import { collectionsDoc, modelsDoc, inspirationDoc } from './screens_library.mjs'
import { filmDoc } from './screens_film.mjs'
import { studioDoc, settingsDoc } from './screens_studio_settings.mjs'
import { tokensDoc } from './screens_tokens.mjs'

const OUT = new URL('./', import.meta.url).pathname
const files = {
  'Main.dc.html': galleryDoc(),
  'PostDetail.dc.html': detailDoc(),
  'Mobile.dc.html': mobileDoc(),
  'Collections.dc.html': collectionsDoc(),
  'Models.dc.html': modelsDoc(),
  'Inspiration.dc.html': inspirationDoc(),
  'Film.dc.html': filmDoc(),
  'Studio.dc.html': studioDoc(),
  'Settings.dc.html': settingsDoc(),
  'Tokens.dc.html': tokensDoc(),
}
for (const [name, html] of Object.entries(files)) writeFileSync(OUT + name, html)

const canvas = {
  pages: [{ id: 'page-1', name: 'Screens' }, { id: 'page-2', name: 'Design system' }],
  artboards: [
    { file: 'Main.dc.html', title: 'Gallery', x: 0, y: 0, w: 1440, h: 1520, page: 'page-1' },
    { file: 'PostDetail.dc.html', title: 'Post detail drawer', x: 1540, y: 0, w: 1440, h: 1500, page: 'page-1' },
    { file: 'Mobile.dc.html', title: 'Gallery · phone', x: 3080, y: 0, w: 390, h: 844, page: 'page-1' },
    { file: 'Collections.dc.html', title: 'Collections', x: 0, y: 1660, w: 1440, h: 1100, page: 'page-1' },
    { file: 'Models.dc.html', title: 'Models', x: 1540, y: 1660, w: 1440, h: 760, page: 'page-1' },
    { file: 'Inspiration.dc.html', title: 'Inspiration · Overview', x: 3080, y: 1660, w: 1440, h: 1080, page: 'page-1' },
    { file: 'Film.dc.html', title: 'Film Studio · Storyboard', x: 0, y: 2900, w: 1440, h: 1540, page: 'page-1' },
    { file: 'Studio.dc.html', title: 'Prompt Studio · Enhance', x: 1540, y: 2900, w: 1440, h: 900, page: 'page-1' },
    { file: 'Settings.dc.html', title: 'Settings', x: 3080, y: 2900, w: 1440, h: 1880, page: 'page-1' },
    { file: 'Tokens.dc.html', title: 'Design tokens & components', x: 0, y: 0, w: 1200, h: 1940, page: 'page-2' },
  ],
  annotations: [
    {
      id: 'sync-loop', x: 0, y: -330, w: 720, page: 'page-1',
      text: 'PromptForge GUI mock — built from the real frontend source (tailwind.config.ts tokens + component markup), so every size, color and radius here is what the container renders.\n\nHow edits reach the container:\n1. Restyle here (tweak chips above each screen, or select any element and change it in the properties panel), then Save.\n2. Tell Claude what changed, or which screen to sync. Claude reads the saved design, maps tweak values to tailwind.config.ts / styles.css and per-element changes to the React components, rebuilds the frontend, runs the tests and commits.\n3. Update the container on Unraid with the promptforge-update script (pull + docker compose build + up -d).\n\nThe tweak chips map 1:1 to the code (see the Design system page). Each screen carries its own chips because artboards are independent — set the same values on the screens you want to compare, or restyle one and ask Claude to apply it everywhere.',
    },
    {
      id: 'placeholders', x: 1540, y: -150, w: 520, page: 'page-1',
      text: 'Artwork is abstract placeholder art (the library media is yours). Counts, prompts and names are sample data. Selected/hover states are shown on one card per screen: the sixth gallery card is in its hover state, shot 1B is selected on the storyboard.',
    },
  ],
  launch: { view: 'canvas', page: 'page-1' },
}
writeFileSync(OUT + 'canvas.json', JSON.stringify(canvas, null, 2))
console.log('generated', Object.keys(files).length, 'artboards')
