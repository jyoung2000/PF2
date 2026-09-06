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

// ---------------------------------------------------------------- Editor ---
export function editorDoc() {
  const msl = (m = false, s = false, l = false) => ['M', 'S', 'L'].map((k, i) => {
    const on = [m, s, l][i]
    const cols = [[P.red300 ?? '#fca5a5', 'rgba(239,68,68,0.3)'], [P.amber300, 'rgba(245,158,11,0.3)'], ['#7dd3fc', 'rgba(14,165,233,0.3)']][i]
    return `<span style="width:20px;height:20px;border-radius:4px;border:1px solid ${on ? cols[0] : T.line};background:${on ? cols[1] : 'transparent'};color:${on ? cols[0] : T.faint};font-size:9.5px;display:inline-flex;align-items:center;justify-content:center">${k}</span>`
  }).join('')
  const clip = (label, x, w, opts = {}) => `<div style="position:absolute;left:${x}px;top:2px;width:${w}px;height:${opts.h ?? 56}px;border:1px solid ${opts.selected ? T.ember : opts.missing ? 'rgba(245,158,11,0.6)' : T.line};background:${opts.selected ? mix(T.ember, 20) : opts.missing ? 'rgba(245,158,11,0.1)' : T.panel};border-radius:${R.el};overflow:hidden;font-size:10.5px;padding:2px 6px;line-height:1.5${opts.selected ? `;box-shadow:0 0 0 1px ${mix(T.ember, 60)}` : ''}">${opts.art != null ? `<div style="position:absolute;inset:0;opacity:0.35">${art(opts.art, 640, 360)}</div>` : ''}<div style="position:relative"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(label)}</div><div style="color:${T.faint};font-variant-numeric:tabular-nums">${opts.dur}${opts.speed ? ` ${opts.speed}×` : ''}</div></div>${opts.transition ? `<span style="position:absolute;right:0;top:0;height:100%;width:5px;background:${mix(T.ember, 70)}"></span>` : ''}</div>`
  const trackRow = (labelTxt, h, msls, laneBg, clips) => `<div style="display:flex"><div style="flex-shrink:0;width:148px;display:flex;align-items:center;gap:4px;padding:0 8px;border-right:1px solid ${T.line};background:${T.well}"><span style="font-family:${F.mono};font-size:11px;color:${T.faint};width:24px">${labelTxt}</span>${msls}</div><div style="position:relative;flex:1;height:${h}px;background:${laneBg};border-radius:${R.el};margin:2px 0">${clips}</div></div>`
  const ruler = Array.from({ length: 9 }, (_, i) => `<span style="position:absolute;left:${148 + i * 130}px;bottom:2px;font-family:${F.mono};font-size:9.5px;color:${T.faint}">0:${String(i * 5).padStart(2, '0')}</span><span style="position:absolute;left:${148 + i * 130}px;top:8px;bottom:0;width:1px;background:${mix(T.faint, 40)}"></span>`).join('')
  const timeline = card(`
    <div style="position:relative;height:26px;border-bottom:1px solid ${T.line};background:${mix(T.well, 60)}">${ruler}</div>
    <div style="position:relative;height:18px"><span style="position:absolute;left:230px;color:#fbbf24;font-size:11px">◆</span><span style="position:absolute;left:520px;color:#f87171;font-size:11px">◆</span><span style="position:absolute;left:8px;font-size:10px;color:${T.faint}">markers</span></div>
    <div style="position:relative">
      ${trackRow('V2', 64, msl(), 'rgba(14,15,18,0.7)', clip('insert · B-roll', 340, 120, { dur: '4.5s', art: 31 }))}
      ${trackRow('V1', 64, msl(), 'rgba(14,15,18,0.7)', [clip('1.1 City at dawn', 8, 150, { dur: '5.5s', art: 27, transition: true }), clip('1.2 Mara wakes', 160, 108, { dur: '4.0s', art: 28, selected: true, speed: '1.5' }), clip('1.3 The package', 272, 84, { dur: '3.0s', art: 29 }), clip('2.1 The chase', 470, 150, { dur: '5.5s', art: 30 }), clip('2.2 Handover', 624, 96, { dur: '3.5s', missing: true })].join(''))}
      ${trackRow('A1', 44, msl(false, false, false), 'rgba(14,15,18,0.4)', clip('synth bed · −6 dB', 8, 300, { dur: '11.0s', h: 36 }))}
      ${trackRow('C1', 34, msl(true), 'rgba(14,15,18,0.25)', clip('“Opening”', 20, 90, { dur: '2.0s', h: 26 }))}
      <div style="position:absolute;left:262px;top:-44px;bottom:0;width:1px;background:#f87171"><span style="position:absolute;top:-2px;left:-4px;color:#f87171;font-size:10px">▼</span></div>
    </div>
  `, 'padding:0;overflow:hidden')
  const num = (l, v, suffix = 's') => `<label style="display:flex;align-items:center;gap:6px;font-size:12px"><span style="color:${T.mute};width:80px;flex-shrink:0">${l}</span>${input(v, { extra: 'height:28px;width:80px;padding-top:0;padding-bottom:0;display:flex;align-items:center;font-variant-numeric:tabular-nums' })}<span style="color:${T.faint}">${suffix}</span></label>`
  const binRow = (n, title, meta, seed, add = true) => `<div style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:6px;display:flex;align-items:center;gap:6px;font-size:11.5px"><div style="width:48px;aspect-ratio:16/9;border-radius:4px;overflow:hidden;background:${T.well}">${seed != null ? art(seed, 320, 180) : ''}</div><div style="flex:1;min-width:0"><div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(title)}</div><div style="color:${T.faint}">${meta}</div></div>${add ? btn('+ Add', { extra: 'font-size:11px;padding:2px 8px' }) : ''}</div>`
  const body = header('Film') + main(`<div style="display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">Film Studio</h1>${select('Night Delivery', { extra: 'max-width:240px' })}${pills(['Projects', 'Assets', 'Story', 'Director', 'Storyboard', 'Timeline', 'Editor'], 'Editor')}</div>
    <div style="display:grid;grid-template-columns:230px minmax(0,1fr) 250px;gap:8px">
      <div style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:8px;display:flex;flex-direction:column;gap:6px">
        <div style="display:flex;gap:4px">${chip('shots', `border-color:${T.ember};color:${T.fg}`)}${chip('footage')}${chip('audio')}</div>
        ${binRow(1, '1.1 City at dawn', '5.5s · take 1 · in timeline', 27)}
        ${binRow(2, '1.2 Mara wakes', '4.0s · take 2 · in timeline', 28)}
        ${binRow(3, '2.2 Handover', '3.5s · no media', null)}
      </div>
      <div style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:10px;display:flex;flex-direction:column;gap:8px">
        <div style="aspect-ratio:16/9;background:${T.ink};border-radius:${R.el};overflow:hidden;position:relative"><div style="position:absolute;inset:0">${art(28, 1280, 720)}</div><div style="position:absolute;left:0;right:0;bottom:16px;text-align:center"><span style="background:rgba(0,0,0,0.7);color:#fff;font-size:14px;padding:2px 8px;border-radius:4px">Opening</span></div><div style="position:absolute;inset:5%;border:1px solid rgba(255,255,255,0.35);pointer-events:none"></div></div>
        <div style="display:flex;align-items:center;gap:6px;font-size:12.5px">${btn('⏮︎', { extra: 'padding:4px 8px' })}${btn('▶', { kind: 'accent', extra: 'padding:4px 12px' })}${btn('⏭︎', { extra: 'padding:4px 8px' })}${chip('loop')}${chip('safe', `border-color:${T.ember};color:${T.fg}`)}<span style="margin-left:auto;font-family:${F.mono};font-size:13px;font-variant-numeric:tabular-nums">00:00:04:12</span><span style="color:${T.faint}">/ 00:00:22:00</span></div>
      </div>
      <div style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:10px;display:flex;flex-direction:column;gap:6px;font-size:12.5px">
        <div style="display:flex;align-items:center;gap:6px"><span style="font-family:${F.display};font-size:13px;flex:1">1.2 Mara wakes</span>${chip('take', 'font-size:10px')}</div>
        ${num('Start', '5.5')}${num('Duration', '4.0')}${num('Trim in', '0.5')}${num('Speed', '1.5', '×')}${num('Fade out', '0.3')}${num('Gain', '0', 'dB')}
        <details open><summary style="font-size:12px;color:${T.mute};cursor:pointer">Effects · <span style="color:${T.ember}">2</span></summary><div style="display:flex;flex-direction:column;gap:4px;margin-top:4px">${num('Scale', '0.8', '')}${num('Opacity', '0.9', '')}</div></details>
        <span style="font-size:11px;color:${T.faint};text-decoration:underline">Open shot in storyboard →</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:12px">${btn('✂ Split')}${btn('Delete')}${btn('Ripple delete')}${chip('🧲 snap', `border-color:${T.ember};color:${T.fg}`)}${btn('◆ Marker')}${btn('T Caption')}<span style="color:${T.line}">|</span>${btn('↩', { extra: 'padding:4px 8px' })}${btn('↪', { disabled: true, extra: 'padding:4px 8px' })}<span style="color:${T.line}">|</span>${btn('−', { extra: 'padding:4px 8px' })}<span style="color:${T.faint};font-variant-numeric:tabular-nums">32px/s</span>${btn('+', { extra: 'padding:4px 8px' })}${btn('QC')}${btn(`Review <span style="background:${T.ember};color:${T.ink};border-radius:9999px;font-size:10px;font-weight:700;padding:0 5px;margin-left:4px">3</span>`)}<span style="margin-left:auto;color:${T.faint}">all changes saved</span>${btn('⌨ shortcuts', { kind: 'ghost' })}${btn('Rebuild from storyboard', { kind: 'ghost' })}</div>
    ${timeline}
  </div>`)
  return document({ title: 'Film Studio · Editor', width: 1440, height: 1080, body })
}
