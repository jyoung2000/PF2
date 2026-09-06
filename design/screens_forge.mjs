import { T, R, F, P, mix, esc, btn, chip, card, input, label, header, main, pills, document } from './lib.mjs'

const CANDIDATES = [
  { name: 'Hailuo / MiniMax', provider: 'wavespeed', score: 75, price: '$0.42', selected: true },
  { name: 'Hailuo / MiniMax', provider: 'fal', score: 75, price: '$0.45' },
  { name: 'Seedance', provider: 'wavespeed', score: 75, price: '$0.56' },
  { name: 'Kling', provider: 'wavespeed', score: 74, price: '$2.30' },
]

function candidate(c) {
  return `<div style="background:${T.panel};border:1px solid ${c.selected ? T.ember : T.line};border-radius:${R.card};padding:12px;cursor:pointer">
    <div style="display:flex;align-items:center;gap:8px"><h3 style="margin:0;font-family:${F.display};font-weight:500;font-size:14px;line-height:1.625">${c.name}</h3>${chip(c.provider, 'font-size:10.5px')}<span style="margin-left:auto;font-family:${F.display};font-size:14px;font-variant-numeric:tabular-nums;color:${T.ember}">${c.score}</span></div>
    <div style="margin-top:4px;display:flex;align-items:center;gap:8px;font-size:11.5px"><span style="color:${P.amber300}">not connected</span><span style="color:${T.faint};font-variant-numeric:tabular-nums">${c.price}</span><span style="color:${T.faint}">priors</span></div>
    <ul style="margin:6px 0 0;padding:0;list-style:none;font-size:11.5px;color:${T.mute};display:flex;flex-direction:column;gap:2px"><li>· declares character consistency</li><li>· accepts reference/image inputs</li><li>· provider not connected — shown for comparison</li></ul>
    <ul style="margin:4px 0 0;padding:0;list-style:none;font-size:11.5px;color:${P.amber300}"><li>⚠ max duration is 10s — request will be clamped</li></ul>
  </div>`
}

export function forgeDoc() {
  const intentChip = (k, v) => chip(`<span style="color:${T.faint}">${k}</span> ${v}`)
  const note = (t) => `<li><span style="color:${T.emberSoft}">◆</span> ${t}</li>`
  const body = header('Forge') + main(`<div style="display:flex;flex-direction:column;gap:16px">
    <div style="display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap"><div><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Forge</h1><p style="margin:0;font-size:12.5px;color:${T.faint}">Idea → model-aware prompt → the right model, explained → generate, compare, refine.</p></div>${pills(['Compose', 'Models', 'Lab', 'Plans', 'Workflows', 'Usage'], 'Compose')}</div>
    ${card(`<div style="display:block;width:100%;min-height:96px;padding:6px 12px;font-size:14.5px;line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el}">Create a cinematic 15-second 9:16 sci-fi trailer with the same character across shots</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px">${intentChip('modality', 'video')}${intentChip('duration', '15s')}${intentChip('aspect', '9:16')}${intentChip('styles', 'cinematic')}${intentChip('consistency', 'character')}${btn('⚒ Forge', { kind: 'accent', extra: 'margin-left:auto' })}</div>`, 'padding:16px')}
    <div style="display:grid;grid-template-columns:340px minmax(0, 1fr);gap:16px;align-items:start">
      <aside style="display:flex;flex-direction:column;gap:8px">${label('Ranked models — every pick explained', 'margin-bottom:0')}${CANDIDATES.map(candidate).join('')}</aside>
      <main style="min-width:0">${card(`
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><h2 style="margin:0;font-family:${F.display};font-weight:500;font-size:15px;line-height:1.625">Hailuo / MiniMax</h2>${chip('wavespeed')}${chip('video')}${chip(`<span style="color:${T.faint}">aspect_ratio</span> 9:16`)}${chip(`<span style="color:${T.faint}">duration_s</span> 10`)}<span style="margin-left:auto;font-size:12.5px;color:${T.faint}">video · 9:16 · 10.0s · est $0.42</span></div>
        <div style="margin-top:12px">${label('Optimized prompt')}<div style="display:block;width:100%;min-height:110px;padding:6px 12px;font-size:13.5px;line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el}">Create a cinematic sci-fi trailer with the same character across shots. slow push in, stabilized camera.</div></div>
        <ul style="margin:12px 0 0;padding:0;list-style:none;font-size:12px;color:${T.mute};display:flex;flex-direction:column;gap:2px">${note('added camera language — this model responds strongly to it')}${note('compiled as flowing natural language')}${note('model guidance: supports bracketed camera directives like [push in], [pan left]')}</ul>
        <p style="margin:10px 0 0;font-size:12px;color:${P.amber300}">⚠ max duration is 10s — request will be clamped</p>
        <p style="margin:8px 0 0;font-size:12px;color:${T.faint}">▶ Evaluation criteria (5) · route reasoning</p>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;border-top:1px solid ${T.line};padding-top:12px;margin-top:12px">${btn('⚡ Generate', { kind: 'accent', disabled: true })}<span style="font-size:12px;color:${P.amber300}">wavespeed not connected — <span style="text-decoration:underline;text-underline-offset:2px">connect it</span> or pick a connected model</span><span style="font-size:12px;color:${T.mute};display:inline-flex;align-items:center;gap:6px"><span style="width:13px;height:13px;border:1px solid ${T.mute};border-radius:3px;display:inline-block"></span> allow fallback provider on failure</span><span style="margin-left:auto;display:flex;gap:8px">${btn('✨ LLM polish')}${btn('Send to Lab')}${btn('Save')}</span></div>`, 'padding:16px')}
      </main>
    </div>
  </div>`)
  return document({ title: 'Forge · Compose', width: 1440, height: 1000, body })
}
