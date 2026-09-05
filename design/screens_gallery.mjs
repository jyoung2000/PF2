import { T, R, F, P, mix, esc, btn, chip, CHIP, INPUT, select, label, header, main, searchGlyph, art, statusDot, document } from './lib.mjs'

export const POSTS = [
  { seed: 1, w: 832, h: 1216, p: 'civitai', fav: true, prompt: 'cinematic portrait of a woman in a rain-soaked neon alley, 85mm, shallow depth of field, volumetric light' },
  { seed: 2, w: 1024, h: 768, p: 'lexica', prompt: 'isometric cyberpunk city block, tilt-shift, clean vector shading' },
  { seed: 3, w: 1280, h: 720, p: 'x', video: true, dur: '0:07', prompt: 'drone shot over a fog-covered pine forest at sunrise, slow dolly forward' },
  { seed: 4, w: 896, h: 1344, p: 'midjourney', prompt: 'editorial fashion portrait, brutalist concrete backdrop, hard noon light' },
  { seed: 5, w: 1024, h: 1024, p: 'tensorart', prompt: 'studio product shot of a matte black espresso machine, softbox reflections' },
  { seed: 6, w: 768, h: 1152, p: 'seaart', hover: true, prompt: 'anime keyframe, girl on a rooftop at blue hour, wind in hair, cel shading, film grain' },
  { seed: 7, w: 1024, h: 1280, p: 'pixai', prompt: 'watercolor fox in a birch forest, loose brushwork, paper texture' },
  { seed: 8, w: 1216, h: 832, p: 'civitai', video: true, dur: '0:12', prompt: 'macro shot of ink dispersing in water, 120fps, backlit' },
  { seed: 9, w: 1024, h: 1024, p: 'lexica', prompt: 'art deco poster of a red monorail crossing a desert, flat colors' },
  { seed: 10, w: 1080, h: 1350, p: 'x', prompt: 'street photography, Tokyo crossing at night, rain reflections, 35mm' },
  { seed: 11, w: 1024, h: 768, p: 'midjourney', prompt: 'ceramic teapot shaped like a sleeping cat, soft morning window light' },
  { seed: 12, w: 832, h: 1216, p: 'tensorart', prompt: 'knight in silver armor standing in a wheat field, golden hour, painterly' },
  { seed: 13, w: 1280, h: 720, p: 'seaart', video: true, dur: '0:05', prompt: 'timelapse of clouds rolling over mountain ridges' },
  { seed: 14, w: 1024, h: 1024, p: 'pixai', prompt: 'cozy reading nook illustration, warm lamp glow, rain on window' },
  { seed: 15, w: 896, h: 1344, p: 'civitai', fav: true, prompt: 'noir detective in a smoky office, venetian blind shadows, high contrast' },
  { seed: 16, w: 1024, h: 768, p: 'lexica', prompt: 'low-poly island floating in a pastel sky' },
  { seed: 17, w: 1280, h: 720, p: 'x', video: true, dur: '0:09', prompt: 'slow orbit around a glass sculpture, caustics on the floor' },
  { seed: 18, w: 1024, h: 1280, p: 'midjourney', prompt: 'botanical illustration of a blue poppy, vintage plate style' },
]

const ROW = 8, GAP = 12
export function postCard(post, colW) {
  const ratio = Math.min(Math.max(post.h / post.w, 0.5), 2.2)
  const cardH = Math.round(colW * ratio)
  const hover = Boolean(post.hover)
  let inner = art(post.seed, post.w, post.h)
  if (hover) {
    inner += `<div style="position:absolute;top:6px;right:6px;display:flex;gap:4px">` +
      `<button style="width:28px;height:28px;border-radius:${R.el};backdrop-filter:blur(8px);background:${mix(T.ink, 60)};border:1px solid ${T.line};display:flex;align-items:center;justify-content:center;font-size:13px;color:${post.fav ? T.ember : T.fg};padding:0;cursor:pointer">${post.fav ? '★' : '☆'}</button>` +
      `<button style="width:28px;height:28px;border-radius:${R.el};backdrop-filter:blur(8px);background:${mix(T.ink, 60)};border:1px solid ${T.line};display:flex;align-items:center;justify-content:center;font-size:12px;color:${T.fg};padding:0;cursor:pointer">🔖</button></div>`
  } else if (post.fav) {
    inner += `<span style="position:absolute;top:6px;left:6px;color:${T.ember};font-size:12px;line-height:1;filter:drop-shadow(0 1px 1px rgb(0 0 0 / 0.6))">★</span>`
  }
  if (post.video) {
    inner += `<span style="${CHIP};position:absolute;bottom:6px;right:6px;background:${mix(T.ink, 70)};backdrop-filter:blur(8px);border-color:${mix(T.line, 80)};color:${T.fg}">▶ ${post.dur}</span>`
  }
  if (hover) {
    inner += `<figcaption style="position:absolute;left:0;right:0;bottom:0;padding:32px 10px 8px;background:linear-gradient(to top, ${mix(T.ink, 90)}, transparent);pointer-events:none"><span style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:11.5px;line-height:1.375;color:${mix(T.fg, 90)}">${esc(post.prompt)}</span></figcaption>`
  }
  return { html: `<figure style="position:relative;width:100%;height:100%;margin:0;border-radius:${R.el};overflow:hidden;background:${T.well};border:1px solid ${mix(T.line, 60)};cursor:zoom-in">${inner}</figure>`, cardH }
}

export function masonry(posts, cols, containerW) {
  const colW = (containerW - GAP * (cols - 1)) / cols
  const items = posts.map((p) => {
    const { html, cardH } = postCard(p, colW)
    const span = Math.max(8, Math.ceil((cardH + GAP) / (ROW + GAP)))
    return `<div style="grid-row-end: span ${span}">${html}</div>`
  }).join('\n')
  return `<div style="display:grid;grid-template-columns:repeat(${cols}, minmax(0, 1fr));grid-auto-rows:${ROW}px;gap:${GAP}px">${items}</div>`
}

export function toggleBtn(text, active = false) {
  const base = `display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:${R.el};border:1px solid ${T.line};background:${T.panel};color:${T.fg};font-size:12.5px;font-weight:500;white-space:nowrap;cursor:pointer`
  const on = `;border-color:${mix(T.ember, 70)};color:${T.ember};background:${mix(T.ember, 10)}`
  return `<button style="${base}${active ? on : ''}">${text}</button>`
}

export function stickyBar({ mobile = false, query = '', favorites = false } = {}) {
  const pad = mobile ? 12 : 20
  const search = `<div style="position:relative;width:100%">${searchGlyph}<div style="${INPUT};padding-left:32px;padding-right:32px;height:40px;font-size:14px;background:${T.panel};display:flex;align-items:center;white-space:pre;overflow:hidden;color:${query ? T.fg : T.faint}">${query ? esc(query) : 'Search prompts, models, tags…  (try  model:flux  or  tag:cyberpunk)'}</div>${query ? `<span style="position:absolute;right:10px;top:50%;transform:translateY(-50%);color:${T.faint};font-size:13px;line-height:1">✕</span>` : ''}</div>`
  const filters = `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">${select('All platforms')}${select('All models')}${select('Images + video')}${select('All techniques')}${select('Any time')}${toggleBtn('★ Favorites', favorites)}${toggleBtn('NSFW')}</div>`
  return `<div style="position:sticky;top:48px;z-index:30;margin:0 -${pad}px;padding:10px ${pad}px;background:${mix(T.ink, 90)};backdrop-filter:blur(8px);border-bottom:1px solid ${mix(T.line, 70)};display:flex;flex-direction:column;gap:8px">${search}${filters}</div>`
}

export function galleryMain({ mobile = false, posts = POSTS, hover = true } = {}) {
  const cols = mobile ? 2 : 5
  const containerW = mobile ? 390 - 24 : 1440 - 40
  const list = hover ? posts : posts.map((p) => ({ ...p, hover: false }))
  return main(`<div>${stickyBar({ mobile })}<div style="padding-top:16px">${masonry(list, cols, containerW)}</div></div>`, { mobile })
}

export function galleryDoc() {
  return document({ title: 'Gallery', width: 1440, height: 1520, body: header('Gallery') + galleryMain() })
}

export function mobileDoc() {
  return document({ title: 'Gallery · mobile', width: 390, height: 844, body: header('Gallery', { mobile: true }) + galleryMain({ mobile: true, posts: POSTS.slice(0, 8), hover: false }) })
}

// ------------------------------------------------------------ post detail ---
function scoreBar(name, pct, contribution) {
  return `<div style="display:flex;align-items:center;gap:8px;font-size:12px"><span style="width:128px;flex-shrink:0;color:${T.mute}">${name}</span><span style="flex:1;height:6px;border-radius:9999px;background:${T.well};overflow:hidden"><span style="display:block;height:100%;width:${pct}%;background:${mix(T.ember, 80)}"></span></span><span style="width:40px;text-align:right;font-variant-numeric:tabular-nums;color:${T.faint}">+${contribution}</span></div>`
}
const smallBtn = (text, opts = {}) => btn(text, { ...opts, extra: `height:28px;padding-top:0;padding-bottom:0;font-size:12px${opts.extra ? ';' + opts.extra : ''}` })
const paramChip = (k, v) => chip(`<span style="color:${T.faint}">${k}</span> ${v}`)

export function detailDoc() {
  const post = POSTS[0]
  const mediaH = 620, mediaW = Math.round((mediaH * post.w) / post.h)
  const sectionLabel = (text, right = '') => `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">${label(text, 'margin-bottom:0')}${right}</div>`
  const copyBtn = btn('Copy', { kind: 'ghost', extra: 'padding:2px 8px;font-size:12px' })
  const drawer = `<aside style="position:absolute;top:0;right:0;bottom:0;z-index:65;width:560px;background:${T.panel};border-left:1px solid ${T.line};box-shadow:0 25px 50px -12px rgb(0 0 0 / 0.6);overflow:hidden;display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 16px;background:${mix(T.panel, 95)};backdrop-filter:blur(8px);border-bottom:1px solid ${T.line};flex-shrink:0"><span style="font-size:12px;color:${T.mute}">Civitai · lumen_ai · 3h ago</span>${btn('✕', { kind: 'ghost', extra: 'padding:4px 8px' })}</div>
    <div style="background:${T.ink};display:flex;align-items:center;justify-content:center;max-height:${mediaH}px;overflow:hidden;flex-shrink:0"><div style="width:${mediaW}px;height:${mediaH}px">${art(post.seed, post.w, post.h)}</div></div>
    <div style="padding:16px 16px 32px;display:flex;flex-direction:column;gap:20px">
      <div style="display:flex;flex-wrap:wrap;gap:6px">${smallBtn('★ Favorited', { extra: `border-color:${mix(T.ember, 70)};color:${T.ember}` })}${smallBtn('🔖 Save')}${smallBtn('Send to Baserow')}${smallBtn('Post to Discord')}${smallBtn('Delete', { extra: 'margin-left:auto' })}</div>
      <section>${sectionLabel('Prompt', copyBtn)}<p style="margin:0;max-width:68ch;font-size:13.5px;line-height:1.625;white-space:pre-wrap;background:${T.well};border:1px solid ${T.line};border-radius:${R.el};padding:12px">${esc(post.prompt)}, wet asphalt reflections, cyan and magenta signage, cinematic color grading, film grain</p></section>
      <section>${sectionLabel('Negative prompt', copyBtn)}<p style="margin:0;max-width:68ch;font-size:12.5px;line-height:1.625;color:${T.mute};white-space:pre-wrap;background:${mix(T.well, 60)};border:1px solid ${T.line};border-radius:${R.el};padding:12px">blurry, low quality, watermark, text, extra fingers, deformed hands</p></section>
      <section>${label('Model &amp; parameters')}<div style="display:flex;flex-wrap:wrap;gap:6px">${chip('Flux.1 Dev', `color:${T.fg};border-color:${mix(T.mute, 40)}`)}${chip('Flux')}${chip('1.0')}${chip('832×1216')}</div><div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">${paramChip('seed', '918273645')}${paramChip('steps', '28')}${paramChip('cfg_scale', '3.5')}${paramChip('sampler', 'euler')}${paramChip('scheduler', 'simple')}</div><div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px">${chip('rim-light', `color:${T.emberSoft};border-color:${mix(T.ember, 30)}`)}${chip('shallow-dof', `color:${T.emberSoft};border-color:${mix(T.ember, 30)}`)}</div></section>
      <div style="display:flex;flex-direction:column;gap:20px">
        <div style="display:flex;flex-wrap:wrap;gap:6px">${smallBtn('Use in Studio')}${smallBtn('✦ Use as Inspiration', { kind: 'accent' })}${smallBtn('🎬 Use in Film')}${smallBtn('Find similar')}${smallBtn('View creator')}</div>
        <section><div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px">${label('Why this is inspiring', 'margin-bottom:0')}<span style="font-family:${F.display};font-size:20px;font-variant-numeric:tabular-nums;color:${T.ember}">84</span></div><div style="display:flex;flex-direction:column;gap:4px">${scoreBar('Visual quality', 88, 22)}${scoreBar('Prompt quality', 92, 18)}${scoreBar('Technical detail', 70, 11)}${scoreBar('Novelty', 64, 9)}${scoreBar('Engagement', 58, 12)}${scoreBar('Model relevance', 100, 8)}${scoreBar('Metadata richness', 80, 4)}</div><p style="margin:6px 0 0;font-size:11.5px;color:${T.faint}">Definitely AI · 96% · candidate score 78</p></section>
        <section>${label('Detected')}<div style="display:flex;flex-wrap:wrap;gap:6px;font-size:12px">${chip('Flux.1 Dev', `color:${T.fg}`)}${chip('85mm')}${chip('medium close-up')}${chip('eye level')}${chip('neon', `color:${mix(P.amber200, 90)}`)}${chip('rule of thirds')}${chip('rim-light', `color:${T.emberSoft};border-color:${mix(T.ember, 30)}`)}${chip('2:3')}</div></section>
      </div>
      <section>${label('Your tags')}<div style="display:flex;flex-wrap:wrap;gap:6px">${chip(`portrait <span style="color:${T.faint};margin-left:2px">✕</span>`, `color:${T.fg}`)}${chip(`neon <span style="color:${T.faint};margin-left:2px">✕</span>`, `color:${T.fg}`)}${chip(`cyberpunk <span style="color:${T.faint};margin-left:2px">✕</span>`, `color:${T.fg}`)}</div><div style="position:relative;margin-top:8px">${select('Add a tag…', { extra: `width:100%;color:${T.faint};font-size:12.5px;height:32px` }).replace(chevronRe, '')}</div></section>
      <section style="font-size:12px;color:${T.faint};display:flex;flex-direction:column;gap:4px;border-top:1px solid ${T.line};padding-top:12px"><p style="margin:0">Source: <a href="#" style="color:${T.mute};text-decoration:underline;text-underline-offset:2px">https://civitai.com/images/91827364</a></p><p style="margin:0">In collections: Moody portraits</p><p style="margin:0">Storage: 412 KB (saved 3.1 MB via compression)</p><p style="margin:0">Scraped · 3h ago</p></section>
    </div>
  </aside>`
  const body = header('Gallery') + galleryMain({ hover: false }) +
    `<div style="position:absolute;inset:0;z-index:60;background:${mix(T.ink, 60)};backdrop-filter:blur(2px)"></div>` + drawer
  return document({ title: 'Post detail', width: 1440, height: 1500, fixedHeight: true, body })
}
const chevronRe = /<svg[^>]*><path d="M3 4.5l3 3 3-3"><\/path><\/svg>/
