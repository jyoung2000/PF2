/**
 * Capture the running PromptForge GUI as a browsable static copy.
 *
 * For every route it loads the real app, waits for it to settle, then writes
 * the rendered DOM to design/preview/<name>.html with the app's own stylesheet,
 * fonts and media copied next to it. The module script is dropped so the pages
 * are static; nothing else about the markup is rewritten except URLs (absolute
 * app paths become relative asset paths) and in-app links (which point at the
 * sibling captures, so the copy browses like the app).
 *
 *   node design/capture.mjs [baseUrl] [outDir]
 */
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'

const require = createRequire('/opt/node22/lib/node_modules/playwright/node_modules/')
const { chromium } = require('playwright-core')

const BASE = process.argv[2] ?? 'http://127.0.0.1:5643'
const OUT = process.argv[3] ?? new URL('./preview/', import.meta.url).pathname

/** name, route, label, group, and how to reach the state worth capturing. */
const SCREENS = [
  { name: 'gallery', route: '/', group: 'Library', label: 'Gallery',
    note: 'Masonry of everything scraped or generated, with search and filters.' },
  { name: 'gallery-detail', route: '/?post=1', group: 'Library', label: 'Post detail',
    note: 'The drawer: prompt, parameters, provenance and why the post scored what it did.', settle: 1500 },
  { name: 'gallery-search', route: '/?q=model%3Aflux', group: 'Library', label: 'Search results',
    note: 'A qualifier search — model:flux — narrowing the same grid.' },
  { name: 'collections', route: '/collections', group: 'Library', label: 'Collections',
    note: 'Your collections plus the model collections the library maintains itself.' },
  { name: 'collection', route: '/collections/1', group: 'Library', label: 'Collection detail',
    note: 'One collection, filtered to its own posts.' },
  { name: 'models', route: '/models', group: 'Library', label: 'Models',
    note: 'Every model family seen, with versions and first/last sightings.' },
  { name: 'inspiration', route: '/inspiration', group: 'Inspiration', label: 'Overview',
    note: 'Pipeline counters and a card per source with its last run.' },
  { name: 'inspiration-sources', route: '/inspiration/sources', group: 'Inspiration', label: 'Sources',
    note: 'Every adapter: connection state, schedule and controls.' },
  { name: 'inspiration-creators', route: '/inspiration/creators', group: 'Inspiration', label: 'Creators',
    note: 'Monitored accounts and the creator intelligence computed from their posts.' },
  { name: 'inspiration-clusters', route: '/inspiration/clusters', group: 'Inspiration', label: 'Clusters',
    note: 'Rule-based clusters over the library — topic, model, technique, style.' },
  { name: 'inspiration-queue', route: '/inspiration/queue', group: 'Inspiration', label: 'Queue',
    note: 'The staged pipeline: enrich, analysis, knowledge.' },
  { name: 'inspiration-analytics', route: '/inspiration/analytics', group: 'Inspiration', label: 'Analytics',
    note: 'Trends and distributions across what has been collected.' },
  { name: 'film-projects', route: '/film', group: 'Film Studio', label: 'Projects',
    note: 'Film projects with their gates and progress.' },
  { name: 'film-assets', route: '/film/assets', group: 'Film Studio', label: 'Assets',
    note: 'Characters, locations, props and styles — versioned, with references.' },
  { name: 'film-story', route: '/film/story', group: 'Film Studio', label: 'Story',
    note: 'Script, scenes and beats.' },
  { name: 'film-director', route: '/film/director', group: 'Film Studio', label: 'Director',
    note: 'Proposals the Director makes; nothing changes until you accept.' },
  { name: 'film-storyboard', route: '/film/storyboard', group: 'Film Studio', label: 'Storyboard',
    note: 'Scenes, shot grid, timeline strip and the shot inspector.', settle: 2000,
    act: async (page) => { await page.locator('[data-shot-card]').first().click(); await page.waitForTimeout(1200) } },
  { name: 'film-timeline', route: '/film/timeline', group: 'Film Studio', label: 'Timeline',
    note: 'Preview, audio, subtitles, QA and export.', settle: 2000 },
  { name: 'film-editor', route: '/film/editor', group: 'Film Studio', label: 'Editor',
    note: 'The multi-track editor: media bin, preview, inspector, timeline with markers and track controls.', settle: 2500,
    act: async (page) => {
      const build = page.locator('[data-testid="btn-build-timeline"]')
      if (await build.count()) { await build.click(); await page.waitForTimeout(1500) }
      await page.locator('[data-testid^="clip-"]').first().dispatchEvent('pointerdown')
      await page.waitForTimeout(600)
    } },
  { name: 'studio-templates', route: '/studio', group: 'Studio', label: 'Templates',
    note: 'Templates learned from each collection.' },
  { name: 'studio-enhance', route: '/studio/enhance', group: 'Studio', label: 'Enhance',
    note: 'Upscale any prompt with the model knowledge file and collection style.' },
  { name: 'studio-saved', route: '/studio/saved', group: 'Studio', label: 'Saved prompts',
    note: 'Prompts kept from templates, enhancement or by hand.' },
  { name: 'settings', route: '/settings', group: 'Settings', label: 'Settings',
    note: 'Every integration, scraper key and library default. Captured unconfigured, as a fresh container starts.' },
  { name: 'forge-compose', route: '/forge', group: 'Forge', label: 'Compose',
    note: 'Idea → intent → ranked models with reasons → the compiled, editable prompt package.', settle: 1200,
    act: async (page) => {
      await page.fill('textarea[aria-label="Your idea"]',
        'Create a cinematic 15-second 9:16 sci-fi trailer with the same character across shots')
      await page.click('text=⚒ Forge')
      await page.waitForTimeout(2500)
    } },
  { name: 'forge-models', route: '/forge/models', group: 'Forge', label: 'Model intelligence',
    note: 'Every family with capability badges, licensing honesty and per-provider prices.' },
  { name: 'forge-lab', route: '/forge/lab/1', group: 'Forge', label: 'Prompt Lab',
    note: 'Versioned variants side by side — run, score, fork, refine with diffs.', settle: 1200 },
  { name: 'forge-plans', route: '/forge/plans/1', group: 'Forge', label: 'Creative plan',
    note: 'One brief, an editable multi-asset pipeline with locks and dependencies.', settle: 1200 },
  { name: 'forge-workflows', route: '/forge/workflows/1', group: 'Forge', label: 'Workflow editor',
    note: 'Node graph over plain JSON, executed through the tool layer with approvals.', settle: 1200 },
  { name: 'forge-usage', route: '/forge/usage', group: 'Forge', label: 'Usage',
    note: 'Cost, latency, success rate and fallback lineage per model × provider.' },
  { name: 'gallery-phone', route: '/', group: 'Responsive', label: 'Gallery on a phone',
    note: 'The same page at 390px.', viewport: { width: 390, height: 844 } },
  { name: 'settings-phone', route: '/settings', group: 'Responsive', label: 'Settings on a phone',
    note: 'Settings at 390px.', viewport: { width: 390, height: 844 } },
]

/** Route → capture file, longest prefix wins, so in-app links keep working. */
const ROUTE_MAP = [
  ['/collections/model/', 'collection.html'], ['/collections/', 'collection.html'],
  ['/collections', 'collections.html'], ['/models', 'models.html'],
  ['/inspiration/sources', 'inspiration-sources.html'], ['/inspiration/creators', 'inspiration-creators.html'],
  ['/inspiration/clusters', 'inspiration-clusters.html'], ['/inspiration/queue', 'inspiration-queue.html'],
  ['/inspiration/analytics', 'inspiration-analytics.html'], ['/inspiration', 'inspiration.html'],
  ['/film/assets', 'film-assets.html'], ['/film/story', 'film-story.html'],
  ['/film/director', 'film-director.html'], ['/film/storyboard', 'film-storyboard.html'],
  ['/film/timeline', 'film-timeline.html'], ['/film/editor', 'film-editor.html'],
  ['/film', 'film-projects.html'],
  ['/forge/models', 'forge-models.html'], ['/forge/lab', 'forge-lab.html'],
  ['/forge/plans', 'forge-plans.html'], ['/forge/workflows', 'forge-workflows.html'],
  ['/forge/usage', 'forge-usage.html'], ['/forge', 'forge-compose.html'],
  ['/studio/enhance', 'studio-enhance.html'], ['/studio/saved', 'studio-saved.html'],
  ['/studio', 'studio-templates.html'], ['/settings', 'settings.html'],
  ['/scrapers', 'inspiration-sources.html'], ['/monitoring', 'inspiration-creators.html'],
]

const assets = new Map() // app path → { rel, body }
const seen = new Set()

function assetPath(url) {
  const p = new URL(url, BASE).pathname
  if (p.startsWith('/assets/')) return 'assets/' + p.slice('/assets/'.length)
  if (p.startsWith('/media/')) return 'assets/media/' + p.slice('/media/'.length)
  if (p.startsWith('/film-media/')) return 'assets/film-media/' + p.slice('/film-media/'.length)
  if (p === '/icon.png') return 'assets/icon.png'
  return null
}

function mapRoute(href) {
  let path
  try { path = new URL(href, BASE) } catch { return null }
  if (path.origin !== new URL(BASE).origin) return null
  const route = path.pathname
  if (route === '/') return 'gallery.html' + (path.search || '')
  for (const [prefix, file] of ROUTE_MAP) if (route === prefix || route.startsWith(prefix + '/')) return file
  return 'gallery.html'
}

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })

// The Film section remembers the current project per browser; pick the seeded
// one so its pages capture with content instead of the "choose a project" state.
await context.addInitScript(() => {
  try { localStorage.setItem('pf.film.project', '1') } catch { /* private mode */ }
})

// Collect every asset the app actually loads — nothing is guessed.
context.on('response', async (res) => {
  const rel = assetPath(res.url())
  if (!rel || rel.endsWith('.js') || seen.has(rel) || !res.ok()) return
  seen.add(rel)
  try { assets.set(rel, await res.body()) } catch { seen.delete(rel) }
})

const captured = []
for (const screen of SCREENS) {
  const page = await context.newPage()
  if (screen.viewport) await page.setViewportSize(screen.viewport)
  await page.goto(BASE + screen.route, { waitUntil: 'networkidle' })
  await page.waitForTimeout(screen.settle ?? 900)
  if (screen.act) await screen.act(page)
  // let lazy images inside the viewport resolve
  await page.evaluate(() => {
    document.querySelectorAll('img[loading="lazy"]').forEach((i) => i.setAttribute('loading', 'eager'))
  })
  await page.waitForTimeout(600)

  const html = await page.evaluate(() => {
    // React drives form state through properties; write it into attributes so
    // the static copy shows the same values the live app does
    document.querySelectorAll('select').forEach((sel) => {
      Array.from(sel.options).forEach((o) => o.toggleAttribute('selected', o.selected))
    })
    document.querySelectorAll('input').forEach((el) => {
      if (el.type === 'checkbox' || el.type === 'radio') el.toggleAttribute('checked', el.checked)
      else if (el.value) el.setAttribute('value', el.value)
    })
    document.querySelectorAll('textarea').forEach((el) => { el.textContent = el.value })
    const doc = document.documentElement.cloneNode(true)
    doc.querySelectorAll('script').forEach((s) => s.remove())
    // over file:// a crossorigin request fails, and the page would render unstyled
    doc.querySelectorAll('link[rel="stylesheet"], link[rel="modulepreload"]').forEach((l) => {
      if (l.rel === 'modulepreload') l.remove()
      else l.removeAttribute('crossorigin')
    })
    // <video> keeps its poster but must not autoplay in a static page
    // no autoplay in a static page, but keep the first frame so players are not blank
    doc.querySelectorAll('video').forEach((v) => { v.removeAttribute('autoplay'); v.setAttribute('preload', 'metadata') })
    return '<!doctype html>\n' + doc.outerHTML
  })
  captured.push({ ...screen, html })
  await page.close()
  process.stdout.write(`captured ${screen.name} (${(html.length / 1024).toFixed(0)} KB)\n`)
}
await browser.close()

// ------------------------------------------------------------- rewriting ---
function rewrite(html) {
  let out = html
  // absolute app asset URLs → the copied files
  out = out.replace(/(src|href|poster)="(\/(?:assets|media|film-media)\/[^"]*|\/icon\.png)"/g,
    (m, attr, url) => `${attr}="${assetPath(url) ?? url}"`)
  out = out.replace(/url\(&quot;?(\/(?:assets|media|film-media)\/[^)"&]*)&quot;?\)/g,
    (m, url) => `url("${assetPath(url) ?? url}")`)
  // in-app links → sibling captures
  out = out.replace(/href="(\/[^"]*)"/g, (m, href) => {
    if (/^\/(assets|media|film-media|api)\//.test(href) || href === '/icon.png') return m
    const mapped = mapRoute(href)
    return mapped ? `href="${mapped}"` : m
  })
  return out
}

rmSync(OUT, { recursive: true, force: true })
mkdirSync(OUT, { recursive: true })
for (const [rel, body] of assets) {
  const target = join(OUT, rel)
  mkdirSync(dirname(target), { recursive: true })
  // the built CSS refers to /assets/<font>.woff2; it now sits beside them
  writeFileSync(target, rel.endsWith('.css')
    ? Buffer.from(body.toString('utf8').replace(/url\(\/assets\//g, 'url(')) : body)
}
for (const c of captured) writeFileSync(join(OUT, `${c.name}.html`),
  `<!-- Static capture of the PromptForge GUI (route ${c.route}). Generated by design/capture.mjs — do not edit by hand. -->\n${rewrite(c.html)}`)

// ----------------------------------------------------------------- index ---
const groups = [...new Set(captured.map((c) => c.group))]
const index = `<!doctype html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="icon" type="image/png" href="assets/icon.png">
<title>PromptForge GUI — browsable copy</title>
<link rel="stylesheet" href="${[...assets.keys()].find((k) => k.endsWith('.css'))}">
</head>
<body>
<div class="min-h-screen flex flex-col">
  <header class="sticky top-0 z-40 bg-ink/85 backdrop-blur border-b border-line">
    <div class="mx-auto max-w-[1700px] px-3 sm:px-5 h-12 flex items-center gap-4">
      <span class="font-display font-bold text-[16px] tracking-tight shrink-0">Prompt<span class="text-ember">Forge</span></span>
      <span class="text-[13px] text-mute">browsable copy of the container GUI</span>
    </div>
  </header>
  <main class="flex-1 mx-auto max-w-[1700px] w-full px-3 sm:px-5 py-4 space-y-8">
    <section class="max-w-measure space-y-2">
      <h1 class="font-display font-medium text-[19px]">Every screen, captured from the running app</h1>
      <p class="text-[13px] text-mute">Each page below is the real rendered markup of the container GUI, saved with the app's own stylesheet, fonts and media. Nothing here is a redrawing: open any page and you are looking at what PromptForge served on port 5643, filled with sample data.</p>
      <p class="text-[12.5px] text-faint">The pages are static, so controls do not respond and nothing talks to a server — but the navigation links work, so you can browse between screens exactly as the app lays them out. Regenerate with <span class="font-mono">design/capture.sh</span>.</p>
    </section>
    ${groups.map((g) => `<section>
      <h2 class="font-display font-medium text-[17px] mb-3">${g}</h2>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        ${captured.filter((c) => c.group === g).map((c) => `<a href="${c.name}.html" class="card p-4 hover:border-mute/50 transition-colors duration-fast block">
          <div class="flex items-baseline gap-2">
            <h3 class="font-display font-medium text-[14.5px]">${c.label}</h3>
            <span class="chip ml-auto">${c.route}</span>
          </div>
          <p class="text-[12.5px] text-faint mt-1">${c.note ?? ''}</p>
        </a>`).join('\n')}
      </div>
    </section>`).join('\n')}
  </main>
</div>
</body>
</html>
`
writeFileSync(join(OUT, 'index.html'), index)
console.log(`\n${captured.length} screens, ${assets.size} assets → ${OUT}`)
