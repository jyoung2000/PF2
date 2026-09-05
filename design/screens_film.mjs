import { T, R, F, P, mix, esc, btn, chip, card, input, select, label, header, main, pills, art, shotDiagram, document } from './lib.mjs'

const SCENES = [
  { n: '01', title: 'Rooftop dawn', shots: 4, tc: '00:18', approved: true, selected: true, gap: null },
  { n: '02', title: 'The chase', shots: 6, tc: '00:38', warn: 2 },
  { n: '03', title: 'Handover', shots: 2, tc: '00:51', gapOverride: '2.5' },
]
const SHOTS = [
  { label: '1A', abbr: 'WS', title: 'City at dawn', dur: 6, loc: 'Rooftop', strategy: 'AI video', takes: 2, status: P.emerald400, seed: 3, media: true },
  { label: '1B', abbr: 'MCU', title: 'Mara wakes', dur: 4, chars: ['Mara'], loc: 'Rooftop', strategy: 'AI video', takes: 2, status: P.emerald300, selected: true, approved: true },
  { label: '1C', abbr: 'CU', title: 'The package', dur: 3, chars: ['Mara'], strategy: 'AI video', takes: 1, status: P.emerald400, locks: 1 },
  { label: '1D', abbr: 'OTS', title: 'She looks out', dur: 5, chars: ['Mara', 'Dispatcher'], loc: 'Rooftop', strategy: 'Image + animation', takes: 0, status: T.faint, warn: 1, transition: 'dissolve' },
]
const DOT = (c) => `<span style="width:8px;height:8px;border-radius:9999px;background:${c};display:inline-block"></span>`
const tag = (text, extra = '') => `<span style="position:absolute;background:${mix(T.ink, 80)};padding:0 4px;border-radius:4px;font-size:10px;line-height:1.625${extra ? ';' + extra : ''}">${text}</span>`

function sceneCard(sc) {
  return `<button style="width:100%;text-align:left;background:${T.panel};border:1px solid ${sc.selected ? T.ember : T.line};border-radius:${R.card};padding:8px;cursor:pointer;color:${T.fg};font-family:${F.body}"><div style="display:flex;align-items:center;gap:6px;font-size:12.5px;line-height:1.625"><span style="font-family:${F.mono};color:${T.faint}">${sc.n}</span><span style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(sc.title)}</span>${sc.approved ? `<span style="color:${P.emerald300};font-size:10px;margin-left:auto">✓</span>` : ''}</div><div style="font-size:10.5px;color:${T.faint};display:flex;gap:6px;line-height:1.625"><span>${sc.shots} shots · ${sc.tc}</span>${sc.warn ? `<span style="color:${P.amber300}">⚠ ${sc.warn}</span>` : ''}</div>${sc.gapOverride ? `<div style="font-size:10px;color:${T.faint}">gap after ${sc.gapOverride}s (override)</div>` : ''}</button>`
}
function shotCard(sh) {
  const media = sh.media ? art(sh.seed, 1280, 720) : `<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%">${shotDiagram(sh.abbr, 160)}</div>`
  const chars = (sh.chars ?? []).map((c) => chip(`👤 ${c}`, 'font-size:10px')).join('')
  return `<div style="background:${T.panel};border:1px solid ${sh.selected ? T.ember : T.line};border-radius:${R.card};padding:8px;cursor:pointer;user-select:none">
    <div style="position:relative;aspect-ratio:16 / 9;border-radius:${R.el};overflow:hidden;background:${T.well};display:flex;align-items:center;justify-content:center">${media}${tag(sh.label, `top:4px;left:4px;font-family:${F.mono};font-size:10.5px`)}<span style="position:absolute;top:4px;right:4px;display:flex;align-items:center;gap:4px">${sh.locks ? `<span style="background:${mix(T.ink, 80)};padding:0 4px;border-radius:4px;font-size:10px;line-height:1.625">🔒${sh.locks}</span>` : ''}${sh.approved ? `<span style="background:${mix(T.ink, 80)};padding:0 4px;border-radius:4px;font-size:10px;line-height:1.625;color:${P.emerald300}">✓</span>` : ''}${DOT(sh.status)}</span>${sh.transition ? tag(`${sh.transition} →`, 'bottom:4px;right:4px') : ''}${sh.warn ? tag(`⚠ ${sh.warn}`, `bottom:4px;left:4px;color:${P.amber300}`) : ''}</div>
    <div style="margin-top:6px;display:flex;align-items:center;gap:6px;font-size:12px">${chip(sh.abbr, 'font-size:10px')}<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(sh.title)}</span><span style="color:${T.faint};font-variant-numeric:tabular-nums">${sh.dur}s</span></div>
    <div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;font-size:10.5px;align-items:center">${chars}${sh.loc ? chip(`📍 ${sh.loc}`, 'font-size:10px') : ''}<span style="color:${T.faint};margin-left:auto">${sh.strategy}${sh.takes ? ` · ${sh.takes} take${sh.takes === 1 ? '' : 's'}` : ''}</span></div>
  </div>`
}
function strip() {
  const px = 26
  const block = (label, d, selected = false, transition = false) => `<div style="position:relative;height:48px;width:${Math.max(28, Math.round(d * px))}px;border:1px solid ${selected ? T.ember : T.line};background:${selected ? mix(T.ember, 15) : T.panel};border-radius:${R.el};margin-right:2px;font-size:10.5px;padding:4px 6px;overflow:hidden;cursor:pointer;line-height:1.625"><div style="font-family:${F.mono};color:${T.faint}">${label}</div><div style="font-variant-numeric:tabular-nums">${d}s</div>${transition ? `<span style="position:absolute;right:0;top:0;height:100%;width:4px;background:${mix(T.ember, 60)}"></span>` : ''}</div>`
  const gap = (s) => `<div style="height:48px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;margin-right:2px;width:${Math.max(14, Math.round(s * px))}px"><div style="width:100%;height:24px;background:${T.ink};border:1px dashed ${T.line};border-radius:${R.el}"></div><div style="font-size:9px;color:${T.faint}">${s}s</div></div>`
  const scene = (n, title, shots) => `<div style="display:flex;flex-direction:column"><div style="font-size:10px;color:${T.faint};margin-bottom:4px;padding:0 4px">S${n} ${title}</div><div style="display:flex">${shots}</div></div>`
  return `<div style="overflow-x:auto;padding-bottom:8px"><div style="display:flex;align-items:flex-end;min-width:max-content">
    <div style="display:flex;align-items:flex-end">${scene('01', 'Rooftop dawn', block('1A', 6) + block('1B', 4, true) + block('1C', 3) + block('1D', 5, false, true))}${gap(1)}</div>
    <div style="display:flex;align-items:flex-end">${scene('02', 'The chase', block('2A', 3) + block('2B', 2) + block('2C', 4) + block('2D', 2) + block('2E', 3) + block('2F', 5))}${gap(1)}</div>
    <div style="display:flex;align-items:flex-end">${scene('03', 'Handover', block('3A', 6) + block('3B', 6))}</div>
  </div></div>`
}
const modeChip = (text, active = false, extra = '') => chip(text, `cursor:pointer${active ? `;border-color:${T.ember};color:${T.fg}` : ''}${extra ? ';' + extra : ''}`)
const small = (text, opts = {}) => btn(text, { ...opts, extra: `font-size:12px${opts.extra ? ';' + opts.extra : ''}` })

function inspector() {
  const take = (n, kind, status, qa, selected) => `<div style="flex-shrink:0;width:96px;border-radius:${R.el};border:1px solid ${selected ? T.ember : T.line};padding:4px;font-size:10.5px;line-height:1.625"><div style="aspect-ratio:16 / 9;background:${T.well};border-radius:${R.el};overflow:hidden;display:flex;align-items:center;justify-content:center">${art(20 + n, 1280, 720)}</div><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">T${n} · ${kind}</div><div style="color:${T.faint};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${status}${qa ? ` · ${qa}` : ''}</div><div style="display:flex;gap:2px;margin-top:2px">${selected ? '' : btn('use', { kind: 'ghost', extra: 'font-size:10px;padding:0 4px' }) + btn('vs', { kind: 'ghost', extra: 'font-size:10px;padding:0 4px' })}</div></div>`
  const row = (name, inner) => `${label(name, 'margin-bottom:0')}<div style="display:flex;flex-wrap:wrap;gap:4px">${inner}</div>`
  const cams = ['Static', 'Push in', 'Pull out', 'Pan', 'Tilt', 'Tracking'].map((c) => modeChip(c, c === 'Push in')).join('')
  const lights = ['Cinematic soft', 'Hard noon', 'Golden hour', 'Blue hour', 'Neon night', 'Horror low-key', 'Studio', 'Overcast'].map((c) => modeChip(c, c === 'Golden hour')).join('')
  const locks = ['camera', 'lighting', 'environment', 'color', 'motion', 'action', 'expression', 'pose', 'timing', 'media strategy'].map((k) => modeChip(`${k === 'lighting' ? '🔒' : '🔓'} ${k}`, k === 'lighting')).join('')
  return card(`
    <div style="display:flex;align-items:center;gap:8px"><span style="font-family:${F.mono};font-size:11px;color:${T.faint}">1B</span>${input('Mara wakes', { extra: `height:32px;padding-top:0;padding-bottom:0;display:flex;align-items:center;font-family:${F.display};flex:1;width:auto` })}${DOT(P.emerald300)}${btn('✕', { kind: 'ghost', extra: 'padding:6px 4px' })}</div>
    <div style="border-radius:${R.el};overflow:hidden;background:${T.ink};aspect-ratio:16 / 9;display:flex;align-items:center;justify-content:center;position:relative">${art(22, 1280, 720)}<span style="position:absolute;bottom:4px;left:4px;background:${mix(T.ink, 80)};padding:0 6px;border-radius:4px;font-size:10.5px;line-height:1.625">take 2 · fal · wan · $0.42 · QA PASS</span></div>
    <div style="display:flex;gap:6px;overflow:hidden;padding-bottom:4px">${take(1, 'text to video', 'succeeded', 'WARN', false)}${take(2, 'image to video', 'succeeded', 'PASS', true)}</div>
    <details style="font-size:11.5px"><summary style="color:${P.amber300};cursor:pointer">⚠ 1 continuity note(s)</summary><ul style="margin:4px 0 0;padding:0;list-style:none"><li style="color:${P.amber300}">Lighting jumps from golden hour (1A) to this shot’s preset<span style="color:${T.faint}"> · match the scene default or lock lighting on both shots (heuristic)</span></li></ul></details>
    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">${btn('Generate video', { kind: 'accent' })}${small('Repair / regenerate…')}${small('Footage')}${small('Import file')}${select('AI video', { extra: 'margin-left:auto;width:160px;font-size:12px' })}</div>
    <section style="display:flex;flex-direction:column;gap:8px">
      <div>${label('Action / prompt')}<div style="display:block;width:100%;min-height:70px;padding:6px 12px;font-size:12.5px;line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el};margin-top:4px">Mara jolts awake on the rooftop cot, city hum below, breath fogging in the cold dawn light</div></div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px">${label('Characters', 'margin-bottom:0')}${chip(`<span style="width:16px;height:16px;border-radius:9999px;background:${T.ember};display:inline-block"></span> Mara <span style="color:${T.faint}">v3</span>`, `color:${T.fg}`)}${btn('edit…', { kind: 'ghost', extra: 'font-size:12px' })}</div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px">${label('Location', 'margin-bottom:0')}${chip(`<span style="width:16px;height:16px;border-radius:9999px;background:${P.amber400};display:inline-block"></span> Rooftop <span style="color:${T.faint}">v1</span>`)}${btn('edit…', { kind: 'ghost', extra: 'font-size:12px' })}${label('Props &amp; style', 'margin-bottom:0;margin-left:8px')}${chip('Courier bag')}${btn('edit…', { kind: 'ghost', extra: 'font-size:12px' })}</div>
      <div style="display:flex;align-items:center;gap:8px">${label('Shot type', 'margin-bottom:0')}<button style="display:flex;align-items:center;gap:8px;border-radius:${R.el};border:1px solid ${T.line};padding:4px;background:transparent;cursor:pointer;color:${T.fg};font-family:${F.body}">${shotDiagram('MCU', 96)}<span style="font-size:12px;text-align:left;line-height:1.625"><b>Medium Close-Up</b><span style="display:block;color:${T.faint}">reactions, dialogue, intimacy</span></span></button></div>
      <div style="display:grid;grid-template-columns:72px minmax(0, 1fr);gap:8px;align-items:center;font-size:12px">
        ${label('Duration', 'margin-bottom:0')}<div style="display:flex;align-items:center;gap:8px">${input('4', { extra: 'width:80px;height:32px;padding-top:0;padding-bottom:0;display:flex;align-items:center;font-variant-numeric:tabular-nums' })}<span style="color:${T.faint}">s</span>${select('transition: default', { extra: 'width:112px;font-size:13px' })}</div>
        ${row('Camera', cams)}
        ${row('Lighting', lights)}
        ${label('Style', 'margin-bottom:0')}${input('inherits project style', { placeholder: true, extra: 'height:32px;padding-top:0;padding-bottom:0;display:flex;align-items:center' })}
      </div>
      <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;font-size:11.5px">${label('Locks', 'margin-bottom:0')}${locks}<span style="color:${T.faint};margin-left:auto;display:inline-flex;align-items:center;gap:4px">approved <span style="width:13px;height:13px;border:1px solid ${T.mute};border-radius:3px;background:${T.ember};display:inline-block"></span></span></div>
    </section>
    <section style="display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:8px">
      ${card(`<div style="display:flex;align-items:center;gap:4px;font-size:11.5px"><span style="font-weight:500">Start frame</span><span style="color:${T.faint};margin-left:auto">generated</span></div><div style="aspect-ratio:16 / 9;background:${T.well};border-radius:${R.el};overflow:hidden;margin-top:4px">${art(24, 1280, 720)}</div>`, `background:${T.well};padding:8px`)}
      ${card(`<div style="display:flex;align-items:center;gap:4px;font-size:11.5px"><span style="font-weight:500">End frame</span><span>🔒</span><span style="color:${T.faint};margin-left:auto">chained ← shot 1A</span></div><div style="aspect-ratio:16 / 9;background:${T.well};border-radius:${R.el};overflow:hidden;margin-top:4px">${art(25, 1280, 720)}</div>`, `background:${T.well};padding:8px`)}
    </section>
    <div style="display:flex;gap:6px">${input('Tell the Director: “make it tense, intimate, expensive, keep Mara’s face”', { placeholder: true, extra: 'height:32px;padding-top:0;padding-bottom:0;display:flex;align-items:center;font-size:12.5px;flex:1;width:auto;white-space:nowrap;overflow:hidden' })}${btn('Ask Director', { disabled: true })}</div>
  `, 'padding:12px;display:flex;flex-direction:column;gap:12px')
}

export function filmDoc() {
  const density = [2, 4, 6, 9].map((d) => modeChip(String(d), d === 4, 'padding-left:6px;padding-right:6px')).join('')
  const body = header('Film') + main(`<div style="display:flex;flex-direction:column;gap:12px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Film Studio</h1>${select('Night Delivery', { extra: 'max-width:240px' })}${pills(['Projects', 'Assets', 'Story', 'Director', 'Storyboard', 'Timeline'], 'Storyboard')}</div>
    <div style="display:grid;grid-template-columns:210px minmax(0, 1fr) 400px;gap:12px">
      <aside style="display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;align-items:center;gap:4px"><h3 style="margin:0;font-family:${F.display};font-weight:500;font-size:13.5px;line-height:1.625">Scenes</h3>${btn('+ scene', { kind: 'ghost', extra: 'font-size:12px;margin-left:auto' })}</div>
        ${SCENES.map(sceneCard).join('')}
        ${card(`${btn('Check continuity', { extra: 'width:100%;justify-content:center;font-size:12px' })}<div style="color:${T.faint}">balanced: 0 block · 2 warn · 5 info</div><div style="color:${T.faint}">spent $3.84 · est $6.10</div>`, 'padding:8px;font-size:11.5px;display:flex;flex-direction:column;gap:4px')}
      </aside>
      <div style="min-width:0;display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><h2 style="margin:0;font-family:${F.display};font-weight:500;font-size:15px;line-height:1.625">01 · Rooftop dawn</h2><span style="font-size:11.5px;color:${T.faint}">Rooftop, Old Town dawn clear</span><div style="margin-left:auto;display:flex;align-items:center;gap:4px">${modeChip('grid', true)}${modeChip('contact sheet')}${density}${small('+ shot')}${small('Direct scene')}</div></div>
        <div style="display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:8px">${SHOTS.map(shotCard).join('')}</div>
        ${card(strip(), 'padding:8px')}
      </div>
      <aside style="min-width:0">${inspector()}</aside>
    </div>
  </div>`)
  return document({ title: 'Film Studio · Storyboard', width: 1440, height: 1540, body })
}
