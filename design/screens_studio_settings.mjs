import { T, R, F, P, mix, esc, btn, chip, card, input, select, label, toggle, connBadge, header, main, document } from './lib.mjs'

// ---------------------------------------------------------------- studio ---
export function studioDoc() {
  const tabs = ['Templates', 'Enhance', 'Saved prompts'].map((t) => `<a href="#" style="padding:6px 16px;font-size:13px;line-height:1.625;text-decoration:none;${t === 'Enhance' ? `background:${T.well};color:${T.fg};font-weight:500` : `color:${T.mute}`}">${t}</a>`).join('')
  const note = (change, why) => `<li style="font-size:12.5px"><span style="color:${T.emberSoft};font-weight:500">${change}</span><span style="color:${T.faint}"> — ${why}</span></li>`
  const body = header('Studio') + main(`<div style="max-width:1024px;margin:0 auto">
    <div style="text-align:center;padding:16px 0 24px"><h1 style="margin:0;font-family:${F.display};font-weight:700;font-size:24px;letter-spacing:-0.025em;line-height:1.625">Prompt Studio</h1><p style="margin:4px 0 0;font-size:13px;color:${T.faint}">Create with learned templates, upscale any prompt, keep the good ones.</p><nav style="display:inline-flex;margin-top:16px;border:1px solid ${T.line};border-radius:${R.el};overflow:hidden">${tabs}</nav></div>
    <div style="max-width:768px;margin:0 auto;display:flex;flex-direction:column;gap:16px">
      <div style="display:block;width:100%;min-height:110px;padding:6px 12px;font-size:14px;line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el}">portrait of an old fisherman, sunset</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${select('Flux', { small: false })}${select('Moody portraits', { small: false })}${btn('✨ Enhance', { kind: 'accent', extra: 'margin-left:auto' })}</div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:12px">
          <div>${label('Before')}<p style="margin:0;background:${mix(T.well, 60)};border:1px solid ${T.line};border-radius:${R.el};padding:12px;font-size:13px;color:${T.mute};white-space:pre-wrap">portrait of an old fisherman, sunset</p></div>
          <div>${label('After')}<p style="margin:0;background:${T.well};border:1px solid ${mix(T.ember, 30)};border-radius:${R.el};padding:12px;font-size:13.5px;white-space:pre-wrap">Weathered portrait of an elderly fisherman at golden hour, salt-worn skin and deep-set eyes, wind-tousled grey beard, oilskin jacket, harbour bokeh behind him, 85mm lens, shallow depth of field, warm rim light, subtle film grain, cinematic color grading</p></div>
        </div>
        <p style="margin:0;font-size:12.5px;color:${T.mute}"><span style="color:${T.faint}">Suggested negative: </span><span style="font-family:${F.mono}">blurry, low quality, watermark, extra fingers, plastic skin</span></p>
        <ul style="margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:4px">${note('Added lens + depth of field', 'Flux responds strongly to camera language (seen in 71% of top prompts)')}${note('Named the light', '“golden hour” anchors the palette the collection favours')}${note('Specified texture', 'tactile detail is the collection’s strongest shared trait')}</ul>
        <div style="display:flex;gap:8px">${btn('Copy')}${btn('Save')}${btn('⚡ Generate', { kind: 'accent' })}</div>
      </div>
    </div>
  </div>`)
  return document({ title: 'Prompt Studio · Enhance', width: 1440, height: 900, body })
}

// -------------------------------------------------------------- settings ---
function section(title, hint, inner) {
  return `<section style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:20px"><h2 style="margin:0;font-family:${F.display};font-weight:500;font-size:15.5px;line-height:1.625">${title}</h2>${hint ? `<p style="margin:2px 0 0;font-size:12.5px;color:${T.faint};max-width:68ch">${hint}</p>` : ''}<div style="margin-top:14px;display:flex;flex-direction:column;gap:12px">${inner}</div></section>`
}
function accountRow(title, badge, detail, controls, first = false) {
  return `<div style="display:grid;grid-template-columns:130px minmax(0, 1fr);gap:16px;align-items:start;padding:${first ? '0' : '12px'} 0 12px;${first ? '' : `border-top:1px solid ${T.line}`}"><div><div style="font-weight:500;font-size:13.5px">${title}</div><div style="margin-top:4px">${connBadge(badge)}</div></div><div style="display:flex;flex-direction:column;gap:8px"><p style="margin:0;font-size:12.5px;color:${T.mute}">${detail}</p><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${controls}</div></div></div>`
}
const field = (name, inner, hint = '') => `<div>${label(name)}${inner}${hint ? `<div style="font-size:12px;color:${T.faint};margin-top:4px">${hint}</div>` : ''}</div>`
const linkBtn = (text) => btn(text, { extra: 'font-size:12px' })
const numberInput = (v, suffix = '') => `<span style="display:inline-flex;align-items:center;gap:6px">${input(v, { extra: 'width:96px;font-variant-numeric:tabular-nums' })}${suffix ? `<span style="font-size:12px;color:${T.faint}">${suffix}</span>` : ''}</span>`

export function settingsDoc() {
  const social = section('Social accounts', 'Connect X for scraping and monitoring, and Grok for the intelligence layer. Use any combination — X only, X + Grok Web, X + Grok API, or all three. Each feature asks only for the credential it needs.',
    accountRow('X', 'connected', 'Your own X login session — powers search crawls and account monitoring. Session: valid.', btn('Reconnect X account') + btn('Disconnect'), true) +
    accountRow('Grok Web', 'not_configured', 'A grok.com browser session captured with the same in-app login. This is NOT an API key and authorises no API feature — it is stored for browser-based Grok features; nothing depends on it yet.', btn('Connect Grok Web', { kind: 'accent' })) +
    accountRow('Grok API', 'connected', 'xAI API key — powers Discover (live X search), Curate, Digest and the “Grok” knowledge-engine provider. Pasting a key saves and tests it in one go; the key is never shown again after saving.', `<span style="width:320px">${input('••••a9f2 stored — paste to replace', { placeholder: true, mono: true })}</span>${linkBtn('Get an API key ↗')}${linkBtn('Test')}${chip('used today: 14', 'font-size:11.5px')}`) +
    `<p style="margin:0;font-size:12.5px;border-radius:${R.el};padding:8px 12px;border:1px solid ${mix(P.emerald400, 30)};color:${P.emerald300};background:${mix(P.emerald400, 10)}">✓ Grok API reachable · grok-4 · 3 models listed</p>` +
    `<div style="font-size:12px;color:${T.faint};border-top:1px solid ${T.line};padding-top:12px;display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));column-gap:24px;row-gap:4px"><span>Search crawls &amp; monitoring → X session</span><span>Find creators / Curate / Digest → Grok API key</span><span>Knowledge provider “Grok” → Grok API key</span><span>Grok Web → optional, no feature requires it yet</span></div>`)
  const scrapers = section('Scrapers', 'Keys and inputs for the content sources.',
    field('Civitai API key (optional)', `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${input('••••7c21 stored — paste to replace', { placeholder: true, mono: true, extra: 'flex:1;width:auto;min-width:220px' })}${linkBtn('Get an API key ↗')}${linkBtn('Test')}${linkBtn('Remove key')}</div><p style="margin:8px 0 0;font-size:12.5px;border-radius:${R.el};padding:8px 12px;border:1px solid ${mix(P.emerald400, 30)};color:${P.emerald300};background:${mix(P.emerald400, 10)}">✓ Connected — key accepted by civitai.com</p>`, 'Higher rate limits + NSFW access. Pasting a key connects immediately — it saves and tests itself (Account settings → API keys on civitai.com).') +
    toggle(false, 'Keep Civitai posts that have no prompt metadata (media-only)') +
    field('Lexica search terms', input('cinematic portrait, isometric city, studio lighting, product photography', { mono: true }), 'Comma-separated; the adapter rotates through them, one per run.'))
  const library = section('Library', 'Browsing defaults and media compression.',
    toggle(false, 'Show NSFW posts by default') +
    `<div style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:12px">${field('Image quality (WebP)', numberInput('82'), '1–100, default 82')}${field('Image max dimension', numberInput('2048', 'px'), 'Longest side in px')}${field('Video CRF', numberInput('27'), 'Lower = larger + sharper, default 27')}${field('Video max height', numberInput('1080', 'px'))}</div>` +
    toggle(false, 'Keep original files alongside compressed copies (uses much more disk)'))
  const stat = (k, v, sub, extra = '') => card(`<dt style="color:${T.faint};font-size:11.5px">${k}</dt><dd style="margin:0;font-family:${F.display};font-size:18px;font-variant-numeric:tabular-nums${extra ? ';' + extra : ''}">${v}</dd>${sub ? `<dd style="margin:0;color:${T.faint};font-size:11.5px;font-variant-numeric:tabular-nums">${sub}</dd>` : ''}`, `background:${T.well};padding:12px`)
  const storage = section('Storage', 'Media is lossy-compressed on ingest; favorites are never purged.',
    `<dl style="margin:0;display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:12px;font-size:13px">${stat('Posts', '4,812', '4,214 img · 598 vid')}${stat('Disk used', '18.6 GB', 'db 212 MB')}${stat('Saved by compression', '41.2 GB', '59.8 GB → 18.6 GB', `color:${P.emerald300}`)}${card(`<dt style="color:${T.faint};font-size:11.5px">Data dir</dt><dd style="margin:0;font-size:12px;font-family:${F.mono};word-break:break-all">/data</dd>`, `background:${T.well};padding:12px`)}</dl>` +
    `<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-top:4px"><span style="font-size:13px;color:${T.mute}">Purge non-favorite posts older than</span>${input('90', { extra: 'width:80px;font-variant-numeric:tabular-nums' })}<span style="font-size:13px;color:${T.mute}">days</span>${btn('Preview purge…')}</div>`)
  const body = header('Settings') + main(`<div style="max-width:768px;display:flex;flex-direction:column;gap:16px;padding-bottom:40px">
    <div><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Settings</h1><p style="margin:0;font-size:12.5px;color:${T.faint}">Everything saves to the app database and applies immediately — no restart. \`.env\` values act as defaults.</p></div>
    ${social}${scrapers}${library}${storage}
  </div>`)
  return document({ title: 'Settings', width: 1440, height: 1880, body })
}
