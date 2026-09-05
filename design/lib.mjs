// Shared vocabulary for the PromptForge design artboards.
// Every value here is lifted from frontend/tailwind.config.ts, src/styles.css
// and the component sources — tokens are exposed as CSS custom properties on
// each artboard root so the tweak chips restyle a whole screen at once.

export const DEF = {
  accent: '#FF6A3D', ink: '#0E0F12', panel: '#15171C', well: '#1C1F26', line: '#272B33',
  fg: '#E9EBEE', mute: '#9BA3AF', faint: '#6B7280', rCard: 14, rEl: 10, fontDisplay: 'Space Grotesk',
}
export const T = {
  ink: 'var(--ink)', panel: 'var(--panel)', well: 'var(--well)', line: 'var(--line)', fg: 'var(--fg)',
  mute: 'var(--mute)', faint: 'var(--faint)', ember: 'var(--ember)', emberSoft: 'var(--ember-soft)',
}
export const R = { card: 'var(--r-card)', el: 'var(--r-el)', chip: 'var(--r-chip)' }
export const F = {
  display: 'var(--font-display)',
  body: 'Inter, system-ui, sans-serif',
  mono: "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace",
}
// Tailwind palette values the app uses literally (emerald/red/amber)
export const P = { emerald300: '#6EE7B7', emerald400: '#34D399', red300: '#FCA5A5', red400: '#F87171', amber200: '#FDE68A', amber300: '#FCD34D', amber400: '#FBBF24' }
export const mix = (v, pct) => `color-mix(in srgb, ${v} ${pct}%, transparent)`
export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

// ---------------------------------------------------------------- atoms ---
export function statusDot(kind, label) {
  const color = kind === 'ok' ? P.emerald400 : kind === 'error' ? P.red400 : kind === 'experimental' ? P.amber400 : T.faint
  return `<span style="display:inline-flex;align-items:center;gap:6px"><span style="width:6px;height:6px;border-radius:9999px;background:${color}"></span>${label ? `<span style="font-size:12px;color:${T.mute}">${esc(label)}</span>` : ''}</span>`
}
const BTN = `display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:${R.el};border:1px solid ${T.line};background:${T.panel};color:${T.fg};font-size:13px;font-weight:500;line-height:1.625;white-space:nowrap;cursor:pointer`
export function btn(label, opts = {}) {
  const { kind = 'default', extra = '', disabled = false } = opts
  let s = BTN
  if (kind === 'accent') s += `;background:${mix(T.ember, 90)};border-color:${T.ember};color:${T.ink};font-weight:600`
  if (kind === 'ghost') s += ';border-color:transparent;background:transparent'
  if (kind === 'danger-active') s += `;border-color:${mix(P.red400, 40)};color:${P.red300}`
  if (disabled) s += ';opacity:0.4'
  return `<button style="${s}${extra ? ';' + extra : ''}">${label}</button>`
}
export const CHIP = `display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:${R.chip};background:${T.well};border:1px solid ${T.line};font-size:12px;color:${T.mute};font-family:${F.mono};font-variant-numeric:tabular-nums;line-height:1.625;white-space:nowrap`
export function chip(label, extra = '') {
  return `<span style="${CHIP}${extra ? ';' + extra : ''}">${label}</span>`
}
export const INPUT = `display:block;width:100%;padding:6px 12px;font-size:13px;line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el};color:${T.fg};font-family:${F.body}`
export function input(value, opts = {}) {
  const { placeholder = false, extra = '', mono = false } = opts
  return `<div style="${INPUT}${mono ? `;font-family:${F.mono}` : ''}${placeholder ? `;color:${T.faint}` : ''}${extra ? ';' + extra : ''}">${value}</div>`
}
export const chevron = (color = T.mute) => `<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="position:absolute;right:8px;top:50%;margin-top:-6px;pointer-events:none"><path d="M3 4.5l3 3 3-3"></path></svg>`
export function select(label, opts = {}) {
  const { extra = '', small = true } = opts
  const size = small ? 'height:32px;padding:0 28px 0 12px;font-size:12.5px' : 'padding:6px 28px 6px 12px;font-size:13px'
  return `<div style="position:relative;display:inline-flex;align-items:center;${size};line-height:1.625;background:${T.well};border:1px solid ${T.line};border-radius:${R.el};color:${T.fg};white-space:nowrap${extra ? ';' + extra : ''}">${esc(label)}${chevron()}</div>`
}
export const LABEL = `display:block;font-size:12px;font-weight:500;color:${T.mute};margin-bottom:4px;line-height:1.625`
export const label = (text, extra = '') => `<span style="${LABEL}${extra ? ';' + extra : ''}">${text}</span>`
export const card = (inner, extra = '') => `<div style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card}${extra ? ';' + extra : ''}">${inner}</div>`
export function toggle(on, text) {
  return `<div style="display:flex;align-items:center;gap:10px;font-size:13px;color:${T.fg};line-height:1.625"><span style="position:relative;width:36px;height:20px;border-radius:9999px;flex-shrink:0;${on ? `background:${T.ember}` : `background:${T.well};border:1px solid ${T.line}`}"><span style="position:absolute;top:${on ? 2 : 1}px;left:${on ? 16 : 1}px;width:16px;height:16px;border-radius:9999px;background:${T.fg}"></span></span><span>${text}</span></div>`
}
export function connBadge(status) {
  const map = {
    connected: ['Connected ✓', `color:${P.emerald300};border-color:${mix(P.emerald400, 40)};background:${mix(P.emerald400, 10)}`],
    error: ['Error', `color:${P.red300};border-color:${mix(P.red400, 40)};background:${mix(P.red400, 10)}`],
    not_configured: ['Not configured', `color:${T.mute};border-color:${T.line};background:${T.well}`],
    offline: ['Offline', `color:${P.amber300};border-color:${mix(P.amber400, 40)};background:${mix(P.amber400, 10)}`],
  }
  const [text, s] = map[status] ?? map.not_configured
  return `<span style="display:inline-flex;padding:2px 8px;border-radius:${R.chip};border:1px solid;font-size:11.5px;font-weight:500;line-height:1.625;${s}">${text}</span>`
}
export const searchGlyph = `<span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);color:${T.faint};font-size:13px;line-height:1">⌕</span>`

// --------------------------------------------------------- placeholder art ---
// Deterministic abstract compositions (no real images — the library's media is
// the user's own). Same spirit as the seeded demo data.
function rng(seed) {
  let s = seed >>> 0 || 1
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return (s % 10000) / 10000 }
}
const BG = ['#2A1F14', '#101B3A', '#1C1329', '#0E2A28', '#2B1420', '#1A2412', '#3A2A0F', '#0F2036', '#25161B', '#14213D', '#2D2A0F', '#171C2E']
const INK = ['#FF6A3D', '#FFB347', '#FFD166', '#06D6A0', '#4CC9F0', '#F72585', '#7209B7', '#4361EE', '#B5179E', '#F9C74F', '#90BE6D', '#F94144', '#43AA8B', '#577590', '#E9C46A', '#FF9F1C', '#CBF3F0', '#2EC4B6', '#E71D36', '#8338EC']
export function art(seed, w, h) {
  const r = rng(seed * 7919 + 17)
  const bg = BG[Math.floor(r() * BG.length)]
  const n = 4 + Math.floor(r() * 4)
  let shapes = ''
  for (let i = 0; i < n; i++) {
    const c = INK[Math.floor(r() * INK.length)]
    const k = r()
    const x = r() * w, y = r() * h
    if (k < 0.4) {
      shapes += `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="${(0.12 * Math.min(w, h) + r() * 0.35 * Math.min(w, h)).toFixed(0)}" fill="${c}" opacity="${(0.75 + r() * 0.25).toFixed(2)}"></circle>`
    } else if (k < 0.75) {
      shapes += `<rect x="${x.toFixed(0)}" y="${y.toFixed(0)}" width="${(0.15 * w + r() * 0.45 * w).toFixed(0)}" height="${(0.1 * h + r() * 0.5 * h).toFixed(0)}" rx="${(r() * 24).toFixed(0)}" fill="${c}" opacity="${(0.7 + r() * 0.3).toFixed(2)}"></rect>`
    } else {
      shapes += `<ellipse cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" rx="${(0.1 * w + r() * 0.4 * w).toFixed(0)}" ry="${(0.06 * h + r() * 0.25 * h).toFixed(0)}" fill="${c}" opacity="${(0.7 + r() * 0.3).toFixed(2)}"></ellipse>`
    }
  }
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid slice" style="width:100%;height:100%;display:block" role="img" aria-label="placeholder artwork"><rect width="${w}" height="${h}" fill="${bg}"></rect>${shapes}</svg>`
}

// Shot-type diagram (original SVG built from the preset descriptor, like the
// app's ShotDiagram): a 16:9 frame with a figure sized by the shot type.
export function shotDiagram(kind, size) {
  const w = size, h = Math.round(size * 9 / 16)
  const cx = w / 2
  const fig = (headR, bodyW, bodyH, baseY, x = cx, color = T.mute) => {
    const headY = baseY - bodyH - headR * 1.15
    return `<circle cx="${x}" cy="${headY.toFixed(1)}" r="${headR}" fill="${color}"></circle><rect x="${(x - bodyW / 2).toFixed(1)}" y="${(baseY - bodyH).toFixed(1)}" width="${bodyW}" height="${bodyH}" rx="${(bodyW / 4).toFixed(1)}" fill="${color}"></rect>`
  }
  let inner = ''
  const u = w / 100
  if (kind === 'WS' || kind === 'EST') {
    inner = `<line x1="0" y1="${h * 0.62}" x2="${w}" y2="${h * 0.62}" stroke="${T.line}" stroke-width="1"></line>` +
      `<rect x="${8 * u}" y="${h * 0.3}" width="${14 * u}" height="${h * 0.32}" fill="${T.well}"></rect><rect x="${70 * u}" y="${h * 0.2}" width="${20 * u}" height="${h * 0.42}" fill="${T.well}"></rect>` +
      fig(2.2 * u, 4 * u, 10 * u, h * 0.62)
  } else if (kind === 'MS') {
    inner = fig(8 * u, 22 * u, 40 * u, h + 8 * u)
  } else if (kind === 'MCU') {
    inner = fig(12 * u, 44 * u, 30 * u, h + 14 * u)
  } else if (kind === 'CU') {
    inner = fig(20 * u, 70 * u, 24 * u, h + 22 * u)
  } else if (kind === 'OTS') {
    inner = `<circle cx="${18 * u}" cy="${h * 0.42}" r="${17 * u}" fill="${T.panel}" stroke="${T.line}"></circle><rect x="${-10 * u}" y="${h * 0.65}" width="${60 * u}" height="${h}" fill="${T.panel}" stroke="${T.line}"></rect>` + fig(9 * u, 26 * u, 30 * u, h + 6 * u, 64 * u)
  } else {
    inner = fig(6 * u, 16 * u, 30 * u, h + 4 * u)
  }
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block" role="img" aria-label="${kind} shot diagram"><rect x="0.5" y="0.5" width="${w - 1}" height="${h - 1}" rx="3" fill="${T.ink}" stroke="${T.line}"></rect><g clip-path="inset(0 round 3px)">${inner}</g><line x1="${w / 3}" y1="0" x2="${w / 3}" y2="${h}" stroke="${T.line}" stroke-dasharray="2 3" opacity="0.6"></line><line x1="${(2 * w) / 3}" y1="0" x2="${(2 * w) / 3}" y2="${h}" stroke="${T.line}" stroke-dasharray="2 3" opacity="0.6"></line></svg>`
}

// ------------------------------------------------------------ app chrome ---
export const NAV = ['Gallery', 'Collections', 'Models', 'Inspiration', 'Film', 'Studio', 'Settings']
export function header(active, { mobile = false, status = true } = {}) {
  const items = NAV.map((n) => {
    const on = n === active
    return `<a href="#" style="padding:0 10px;height:100%;display:inline-flex;align-items:center;font-size:13px;white-space:nowrap;border-bottom:2px solid ${on ? T.ember : 'transparent'};color:${on ? T.fg : T.mute};font-weight:${on ? 500 : 400};text-decoration:none">${n}</a>`
  }).join('')
  const dots = status && !mobile
    ? `<div style="margin-left:auto;display:flex;align-items:center;gap:12px;font-size:12px;color:${T.faint}">${statusDot('ok', 'Baserow')}${statusDot('off', 'Discord')}${statusDot('ok', 'AI')}</div>`
    : ''
  return `<header style="position:sticky;top:0;z-index:40;background:${mix(T.ink, 85)};backdrop-filter:blur(8px);border-bottom:1px solid ${T.line}"><div style="margin:0 auto;max-width:1700px;padding:0 ${mobile ? 12 : 20}px;height:48px;display:flex;align-items:center;gap:16px"><a href="#" style="font-family:${F.display};font-weight:700;font-size:16px;letter-spacing:-0.025em;flex-shrink:0;color:${T.fg};text-decoration:none">Prompt<span style="color:${T.ember}">Forge</span></a><nav style="display:flex;align-items:center;gap:2px;height:100%;margin-bottom:-1px;overflow:hidden;min-width:0">${items}</nav>${dots}</div></header>`
}
export const main = (inner, { mobile = false, extra = '' } = {}) => `<main style="flex:1;margin:0 auto;max-width:1700px;width:100%;padding:16px ${mobile ? 12 : 20}px${extra ? ';' + extra : ''}">${inner}</main>`

// Section-level sub nav used by Inspiration and Film (pill style)
export function pills(items, active) {
  return `<nav style="display:flex;align-items:center;gap:2px;margin-left:auto;overflow:hidden">${items.map((t) => `<a href="#" style="padding:6px 10px;font-size:13px;line-height:1.625;border-radius:${R.el};white-space:nowrap;text-decoration:none;${t === active ? `background:${T.well};color:${T.fg};font-weight:500` : `color:${T.mute}`}">${t}</a>`).join('')}</nav>`
}

// --------------------------------------------------------------- document ---
const PROPS = {
  accent: { editor: 'color', default: DEF.accent, section: 'Colors', options: ['#FF6A3D', '#F4B942', '#4CC9F0', '#C77DFF'] },
  ink: { editor: 'color', default: DEF.ink, section: 'Colors' },
  panel: { editor: 'color', default: DEF.panel, section: 'Colors' },
  well: { editor: 'color', default: DEF.well, section: 'Colors' },
  line: { editor: 'color', default: DEF.line, section: 'Colors' },
  fg: { editor: 'color', default: DEF.fg, section: 'Colors' },
  mute: { editor: 'color', default: DEF.mute, section: 'Colors' },
  faint: { editor: 'color', default: DEF.faint, section: 'Colors' },
  rCard: { editor: 'int', default: DEF.rCard, min: 0, max: 28, unit: 'px', section: 'Shape' },
  rEl: { editor: 'int', default: DEF.rEl, min: 0, max: 20, unit: 'px', section: 'Shape' },
  fontDisplay: { editor: 'enum', default: DEF.fontDisplay, options: ['Space Grotesk', 'Inter', 'Sora', 'Manrope'], section: 'Type' },
}
const LOGIC = `class Component extends DCLogic {
  renderVals() {
    const p = this.props || {};
    const hex = (v, d) => (typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v) ? v : d);
    const accent = hex(p.accent, '${DEF.accent}');
    const n = parseInt(accent.slice(1), 16);
    const ch = (x) => Math.round(x + (255 - x) * 0.2).toString(16).padStart(2, '0');
    const accentSoft = '#' + ch((n >> 16) & 255) + ch((n >> 8) & 255) + ch(n & 255);
    const fonts = {
      'Space Grotesk': "'Space Grotesk', Inter, system-ui, sans-serif",
      'Inter': "Inter, system-ui, sans-serif",
      'Sora': "Sora, Inter, system-ui, sans-serif",
      'Manrope': "Manrope, Inter, system-ui, sans-serif",
    };
    const rEl = Number.isFinite(p.rEl) ? p.rEl : ${DEF.rEl};
    return {
      accent, accentSoft,
      ink: hex(p.ink, '${DEF.ink}'), panel: hex(p.panel, '${DEF.panel}'), well: hex(p.well, '${DEF.well}'),
      line: hex(p.line, '${DEF.line}'), fg: hex(p.fg, '${DEF.fg}'), mute: hex(p.mute, '${DEF.mute}'), faint: hex(p.faint, '${DEF.faint}'),
      rCard: Number.isFinite(p.rCard) ? p.rCard : ${DEF.rCard}, rEl, rChip: Math.max(2, Math.round(rEl * 0.6)),
      fontDisplay: fonts[p.fontDisplay] || fonts['Space Grotesk'],
    };
  }
}`

export function document({ width, height, body, fixedHeight = false, title }) {
  const props = { ...PROPS, $preview: { width, height } }
  const rootStyle = [
    `--ink: {{ink}}`, `--panel: {{panel}}`, `--well: {{well}}`, `--line: {{line}}`, `--fg: {{fg}}`, `--mute: {{mute}}`, `--faint: {{faint}}`,
    `--ember: {{accent}}`, `--ember-soft: {{accentSoft}}`, `--r-card: {{rCard}}px`, `--r-el: {{rEl}}px`, `--r-chip: {{rChip}}px`, `--font-display: {{fontDisplay}}`,
    `width:${width}px`, fixedHeight ? `height:${height}px;overflow:hidden` : `min-height:${height}px`,
    `background:var(--ink)`, `color:var(--fg)`, `font-family:${F.body}`, `font-size:14px`, `line-height:1.625`,
    `-webkit-font-smoothing:antialiased`, `position:relative`, `display:flex`, `flex-direction:column`,
  ].join(';')
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>${esc(title)}</title>
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=Space+Grotesk:wght@500;700&amp;family=JetBrains+Mono:wght@400;500&amp;family=Sora:wght@500;700&amp;family=Manrope:wght@500;700&amp;display=swap">
  <style>
    body { margin: 0; background: #0E0F12; color-scheme: dark; }
    * { box-sizing: border-box; }
    a { color: #9BA3AF; } a:hover { color: #FF6A3D; }
    button { font: inherit; }
    ::selection { background: rgba(255, 106, 61, 0.3); }
  </style>
</helmet>
<div style="${rootStyle}">
${body}
</div>
</x-dc>
<script data-dc-script data-props='${JSON.stringify(props)}'>
${LOGIC}
</script>
</body>
</html>
`
}
