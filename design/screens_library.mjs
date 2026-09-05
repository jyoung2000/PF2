import { T, R, F, P, mix, esc, btn, chip, card, header, main, pills, art, statusDot, document } from './lib.mjs'

// ---------------------------------------------------------- collections ---
function mosaic(seeds) {
  const cells = Array.from({ length: 4 }, (_, i) => seeds[i] != null
    ? `<div style="overflow:hidden">${art(seeds[i], 400, 300)}</div>`
    : `<div style="background:${T.well}"></div>`).join('')
  return `<div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));grid-template-rows:repeat(2, minmax(0, 1fr));gap:1px;background:${T.line};aspect-ratio:4 / 3;overflow:hidden">${cells}</div>`
}
const USER_COLLECTIONS = [
  { name: 'Moody portraits', count: 24, model: 'Flux', seeds: [1, 15, 4, 10] },
  { name: 'Isometric cities', count: 12, model: 'SDXL', mixed: true, seeds: [2, 16, 9, 5] },
  { name: 'Neon noir video', count: 8, model: 'Wan 2.2', seeds: [3, 17, 13] },
  { name: 'Product hero shots', count: 31, model: 'Midjourney', seeds: [5, 11, 14, 18] },
  { name: 'Anime keyframes', count: 17, model: 'Illustrious', seeds: [6, 7, 12, 14] },
]
const MODEL_COLLECTIONS = [
  { label: 'Flux', img: 412, vid: 9, versions: ['flux.1-dev', 'flux.1-schnell', 'flux.1-pro'], seeds: [1, 15, 12, 10] },
  { label: 'SDXL', img: 388, vid: 0, versions: ['1.0', 'turbo', 'lightning'], seeds: [2, 9, 16, 5] },
  { label: 'Midjourney', img: 214, vid: 0, versions: ['v7', 'v6.1', 'niji 6'], seeds: [4, 11, 18, 14] },
  { label: 'Wan', img: 0, vid: 96, versions: ['2.2', '2.1'], seeds: [3, 13, 17, 8] },
  { label: 'Illustrious', img: 177, vid: 0, versions: ['xl-1.0', 'xl-2.0'], seeds: [6, 7, 12, 14] },
  { label: 'Kling', img: 0, vid: 44, versions: ['2.1', '1.6'], seeds: [17, 3, 13] },
  { label: 'Veo', img: 0, vid: 28, versions: ['3'], seeds: [8, 17] },
  { label: 'Stable Diffusion 1.5', img: 301, vid: 0, versions: ['1.5', 'dreamshaper 8'], seeds: [9, 16, 2, 11] },
  { label: 'Hunyuan', img: 0, vid: 19, versions: ['video 1.5'], seeds: [13, 8] },
  { label: 'Pony', img: 95, vid: 0, versions: ['v6 xl'], seeds: [7, 6, 14] },
]
const h2 = (text, extra = '') => `<h2 style="margin:0;font-family:${F.display};font-weight:500;font-size:17px;line-height:1.625${extra ? ';' + extra : ''}">${text}</h2>`
function userCard(c) {
  return card(`${mosaic(c.seeds)}<div style="padding:12px"><div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px"><h3 style="margin:0;font-family:${F.display};font-weight:500;font-size:14.5px;line-height:1.625;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.name)}</h3>${chip(String(c.count), 'flex-shrink:0')}</div><p style="margin:2px 0 0;font-size:12px;color:${T.faint}">${esc(c.model)}${c.mixed ? ' · mixed' : ''}</p></div>`, 'overflow:hidden;position:relative')
}
function modelCard(m) {
  const count = `${m.img} img${m.vid > 0 ? ` · ${m.vid} vid` : ''}`
  const versions = m.versions.slice(0, 3).map((v) => chip(esc(v), 'font-size:11px')).join('')
  return card(`${mosaic(m.seeds)}<div style="padding:12px"><div style="display:flex;align-items:baseline;justify-content:space-between;gap:8px"><h3 style="margin:0;font-family:${F.display};font-weight:500;font-size:14.5px;line-height:1.625;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(m.label)}</h3>${chip(count, 'flex-shrink:0')}</div><div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;max-height:44px;overflow:hidden">${versions}</div></div>`, 'overflow:hidden')
}
const grid5 = (inner) => `<div style="display:grid;grid-template-columns:repeat(5, minmax(0, 1fr));gap:12px">${inner}</div>`
export function collectionsDoc() {
  const body = header('Collections') + main(`<div style="display:flex;flex-direction:column;gap:32px">
    <section><div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">${h2('My collections')}${btn('＋ New collection', { kind: 'accent' })}</div>${grid5(USER_COLLECTIONS.map(userCard).join(''))}</section>
    <section>${h2('Model collections', 'margin-bottom:4px')}<p style="margin:0 0 12px;font-size:12.5px;color:${T.faint}">Automatic — every model family seen in your library, kept current as new posts arrive.</p>${grid5(MODEL_COLLECTIONS.map(modelCard).join(''))}</section>
  </div>`)
  return document({ title: 'Collections', width: 1440, height: 1100, body })
}

// ---------------------------------------------------------------- models ---
const MODELS = [
  { label: 'Flux', posts: 421, img: 412, vid: 9, first: '3 months ago', last: '2h ago', versions: ['flux.1-dev', 'flux.1-schnell', 'flux.1-pro', 'flux.1-kontext', 'flux.2'] },
  { label: 'SDXL', posts: 388, img: 388, vid: 0, first: '3 months ago', last: '5h ago', versions: ['1.0', 'turbo', 'lightning'] },
  { label: 'Wan', posts: 96, img: 0, vid: 96, first: '6 days ago', last: '40m ago', isNew: true, versions: ['2.2', '2.1'] },
  { label: 'Midjourney', posts: 214, img: 214, vid: 0, first: '2 months ago', last: '1d ago', versions: ['v7', 'v6.1', 'niji 6'] },
  { label: 'Illustrious', posts: 177, img: 177, vid: 0, first: '1 month ago', last: '3h ago', versions: ['xl-1.0', 'xl-2.0'] },
  { label: 'Kling', posts: 44, img: 0, vid: 44, first: '9 days ago', last: '6h ago', isNew: true, versions: ['2.1', '1.6'] },
  { label: 'Veo', posts: 28, img: 0, vid: 28, first: '12 days ago', last: '2d ago', isNew: true, versions: ['3'] },
  { label: 'Stable Diffusion 1.5', posts: 301, img: 301, vid: 0, first: '3 months ago', last: '3d ago', versions: ['1.5', 'dreamshaper 8', 'realistic vision 6'] },
  { label: 'Hunyuan', posts: 19, img: 0, vid: 19, first: '3 weeks ago', last: '1d ago', versions: ['video 1.5'] },
]
function modelMetaCard(m) {
  const chips = m.versions.slice(0, 4).map((v) => chip(esc(v), 'font-size:11px')).join('') + (m.versions.length > 4 ? chip(`+${m.versions.length - 4}`, 'font-size:11px') : '')
  const isNew = m.isNew ? chip('NEW', `font-size:10.5px;color:${T.ember};border-color:${mix(T.ember, 50)};background:${mix(T.ember, 10)};font-weight:600`) : ''
  return card(`<div style="display:flex;align-items:center;gap:8px"><h2 style="margin:0;font-family:${F.display};font-weight:500;font-size:15px;line-height:1.625">${esc(m.label)}</h2>${isNew}${chip(`${m.posts} post${m.posts === 1 ? '' : 's'}`, 'margin-left:auto')}</div><p style="margin:4px 0 0;font-size:12px;color:${T.faint};font-variant-numeric:tabular-nums">${m.img} images · ${m.vid} videos · first seen ${m.first} · last ${m.last}</p>${m.versions.length ? `<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">${chips}</div>` : ''}`, 'padding:16px')
}
export function modelsDoc() {
  const body = header('Models') + main(`<div><div style="margin-bottom:16px"><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Models</h1><p style="margin:0;font-size:12.5px;color:${T.faint}">Every model family seen in your library — fully data-driven, new models surface here the moment posts arrive. Click one to browse its collection.</p></div><div style="display:grid;grid-template-columns:repeat(3, minmax(0, 1fr));gap:12px">${MODELS.map(modelMetaCard).join('')}</div></div>`)
  return document({ title: 'Models', width: 1440, height: 760, body })
}

// ----------------------------------------------------------- inspiration ---
const SOURCES = [
  { label: 'Civitai', status: 'ok', statusLabel: 'ok', connected: true, last: '4m ago', next: 'in 6m', found: 120, kept: 37, filtered: 61, dupes: 22, report: '1,932 posts · prompts 96% · metadata 71% · enriched 18% · AI 100% · efficiency 0.31', rec: 'Raise priority: high prompt yield, 12% duplicates.' },
  { label: 'Lexica', status: 'experimental', statusLabel: 'experimental', connected: true, last: '11m ago', next: 'in 4m', found: 60, kept: 9, filtered: 44, dupes: 7, report: '644 posts · prompts 100% · metadata 0% · enriched 0% · AI 100% · efficiency 0.15' },
  { label: 'Midjourney Explore', browser: true, status: 'off', statusLabel: 'needs setup', connected: false, last: 'never', next: 'in 58m', found: 0, kept: 0, filtered: 0, dupes: 0, needsSetup: true },
  { label: 'TensorArt', browser: true, status: 'ok', statusLabel: 'ok', connected: true, last: '38m ago', next: 'in 22m', found: 48, kept: 21, filtered: 19, dupes: 8, report: '512 posts · prompts 88% · metadata 64% · enriched 9% · AI 100% · efficiency 0.44' },
  { label: 'SeaArt', browser: true, status: 'ok', statusLabel: 'ok', connected: true, last: '52m ago', next: 'in 8m', found: 40, kept: 12, filtered: 25, dupes: 3, report: '301 posts · prompts 79% · metadata 41% · enriched 6% · AI 100% · efficiency 0.30' },
  { label: 'PixAI', browser: true, status: 'ok', statusLabel: 'ok', connected: true, paused: true, last: '2d ago', next: 'paused', found: 40, kept: 4, filtered: 33, dupes: 3, report: '188 posts · prompts 92% · metadata 12% · enriched 2% · AI 100% · efficiency 0.10' },
  { label: 'X (Twitter)', browser: true, status: 'ok', statusLabel: 'running', connected: true, last: '1m ago', next: 'in 59m', found: 84, kept: 26, filtered: 47, dupes: 11, report: '1,235 posts · prompts 41% · metadata 3% · enriched 33% · AI 87% · efficiency 0.31', rec: 'Keep: best enrichment yield of all sources.' },
]
const sourceBtn = (text, disabled = false) => btn(text, { extra: 'height:28px;padding-top:0;padding-bottom:0;font-size:12px', disabled })
function sourceCard(s) {
  const dl = [['discovered', s.found], ['kept', s.kept, P.emerald300], ['filtered', s.filtered], ['dupes', s.dupes]]
    .map(([k, v, c]) => `<div><dt style="color:${T.faint}">${k}</dt><dd style="margin:0${c ? `;color:${c}` : ''}">${v}</dd></div>`).join('')
  return card(`<div style="display:flex;align-items:center;gap:8px"><h3 style="margin:0;font-family:${F.display};font-weight:500;font-size:14.5px;line-height:1.625">${esc(s.label)}</h3>${s.browser ? chip('browser', 'font-size:10px') : ''}<span style="margin-left:auto">${statusDot(s.status, s.statusLabel)}</span></div>
    <p style="margin:0;font-size:11.5px;color:${T.faint}">${s.connected ? `<span style="color:${P.emerald300}">connected</span>` : `<span style="color:${P.amber300}">not connected</span>`} · last ${s.last} · next ${s.next}</p>
    <dl style="margin:0;display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:4px;font-size:11.5px;font-variant-numeric:tabular-nums">${dl}</dl>
    ${s.report ? `<p style="margin:0;font-size:11.5px;color:${T.mute};font-variant-numeric:tabular-nums">${s.report}</p>` : ''}
    ${s.rec ? `<p style="margin:0;font-size:11.5px;color:${T.emberSoft}">${s.rec}</p>` : ''}
    <div style="display:flex;gap:6px;margin-top:auto;padding-top:4px">${sourceBtn('▶ Run now', Boolean(s.needsSetup))}${sourceBtn(s.paused ? '▶ Resume' : '⏸ Pause')}</div>`,
    `padding:14px;display:flex;flex-direction:column;gap:8px${s.paused ? ';opacity:0.7' : ''}`)
}
export function inspirationDoc() {
  const stats = [['Posts', '4,812'], ['With prompt', '3,904'], ['With metadata', '1,977'], ['Enriched', '612'], ['Analyzed', '388'], ['Queue', '27']]
    .map(([k, v]) => card(`<div style="font-size:11px;color:${T.faint}">${k}</div><div style="font-family:${F.display};font-size:20px;font-variant-numeric:tabular-nums">${v}</div>`, `background:${T.well};padding:12px`)).join('')
  const body = header('Inspiration') + main(`<div style="display:flex;flex-direction:column;gap:16px">
    <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap"><div><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Inspiration</h1><p style="margin:0;font-size:12.5px;color:${T.faint}">Discover → verify → enrich → score → cluster → learn. Evidence-driven, never just “more posts”.</p></div>${pills(['Overview', 'Sources', 'Creators', 'Clusters', 'Queue', 'Analytics'], 'Overview')}</div>
    <div style="display:grid;grid-template-columns:repeat(6, minmax(0, 1fr));gap:8px">${stats}</div>
    <div style="display:grid;grid-template-columns:repeat(3, minmax(0, 1fr));gap:12px">${SOURCES.map(sourceCard).join('')}</div>
    ${card(`<h3 style="margin:0 0 4px;font-family:${F.display};font-weight:500;font-size:14px;line-height:1.625">Recent pipeline errors</h3><ul style="margin:0;padding:0;list-style:none;font-size:12px;color:${mix(P.red300, 90)};display:flex;flex-direction:column;gap:2px"><li>enrich · post 4801 · X detail capture timed out after 30s</li><li>analysis · post 4788 · provider returned malformed JSON (retry 2/3)</li></ul>`, 'padding:14px')}
  </div>`)
  return document({ title: 'Inspiration', width: 1440, height: 1080, body })
}
