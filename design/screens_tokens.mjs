import { DEF, T, R, F, P, mix, btn, chip, input, select, label, toggle, connBadge, statusDot, document } from './lib.mjs'

export function tokensDoc() {
  const swatch = (name, v, key, where) => `<div style="display:flex;flex-direction:column;gap:6px;width:118px"><div style="height:56px;border-radius:${R.el};background:${v};border:1px solid ${T.line}"></div><div style="font-size:12.5px;font-weight:500">${name}</div><div style="font-family:${F.mono};font-size:11px;color:${T.mute}">${key}</div><div style="font-size:11px;color:${T.faint}">${where}</div></div>`
  const colors = [
    ['ink', T.ink, 'colors.ink', 'page ground'], ['panel', T.panel, 'colors.panel', 'cards, header, drawer'], ['well', T.well, 'colors.well', 'inputs, chips, sunken'], ['line', T.line, 'colors.line', 'hairline borders'],
    ['fg', T.fg, 'colors.fg', 'primary text'], ['mute', T.mute, 'colors.mute', 'secondary text'], ['faint', T.faint, 'colors.faint', 'tertiary text'], ['ember', T.ember, 'colors.ember', 'the one accent'], ['ember-soft', T.emberSoft, 'colors.ember-soft', 'accent on dark text'],
  ].map((c) => swatch(...c)).join('')
  const type = [
    ['Display 24 / 700', 'Prompt Studio', `font-family:${F.display};font-weight:700;font-size:24px;letter-spacing:-0.025em`],
    ['Display 19 / 500', 'Inspiration · Models · Settings', `font-family:${F.display};font-weight:500;font-size:19px`],
    ['Display 17 / 500', 'My collections', `font-family:${F.display};font-weight:500;font-size:17px`],
    ['Display 15.5 / 500', 'Settings section title', `font-family:${F.display};font-weight:500;font-size:15.5px`],
    ['Display 14.5 / 500', 'Card title', `font-family:${F.display};font-weight:500;font-size:14.5px`],
    ['Body 14 / 400', 'Base body text, line-height 1.625', 'font-size:14px'],
    ['Body 13.5', 'Prompt text in the detail drawer', 'font-size:13.5px'],
    ['Body 13 / 500', 'Buttons, inputs', 'font-size:13px;font-weight:500'],
    ['Body 12.5', 'Hints, filter selects, sub nav', `font-size:12.5px;color:${T.faint}`],
    ['Body 12 / 500', 'Field labels', `font-size:12px;font-weight:500;color:${T.mute}`],
    ['Body 11.5', 'Source card metrics, badges', `font-size:11.5px;color:${T.mute}`],
    ['Mono 12', 'chip · seed 918273645 · 832×1216', `font-family:${F.mono};font-size:12px;color:${T.mute}`],
  ].map(([n, sample, s]) => `<div style="display:grid;grid-template-columns:150px minmax(0, 1fr);gap:16px;align-items:baseline;padding:6px 0;border-bottom:1px solid ${T.line}"><span style="font-size:11px;color:${T.faint};font-family:${F.mono}">${n}</span><span style="${s}">${sample}</span></div>`).join('')
  const radii = [['card', R.card, 'cards, sections, drawer menus · default 14px'], ['el', R.el, 'buttons, inputs, thumbnails · default 10px'], ['chip', R.chip, 'chips, badges · 60% of the element radius']]
    .map(([n, r, d]) => `<div style="display:flex;align-items:center;gap:12px"><div style="width:56px;height:40px;border-radius:${r};background:${T.well};border:1px solid ${T.mute}"></div><div><div style="font-size:12.5px;font-weight:500">rounded-${n}</div><div style="font-size:11px;color:${T.faint}">${d}</div></div></div>`).join('')
  const h = (t) => `<h2 style="margin:0 0 12px;font-family:${F.display};font-weight:500;font-size:15.5px;line-height:1.625">${t}</h2>`
  const block = (title, inner, extra = '') => `<section style="background:${T.panel};border:1px solid ${T.line};border-radius:${R.card};padding:20px${extra ? ';' + extra : ''}">${h(title)}${inner}</section>`
  const row = (name, inner) => `<div style="display:grid;grid-template-columns:140px minmax(0, 1fr);gap:16px;align-items:center;padding:8px 0;border-bottom:1px solid ${T.line}"><span style="font-size:11px;color:${T.faint};font-family:${F.mono}">${name}</span><div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">${inner}</div></div>`
  const components =
    row('.btn', btn('Default') + btn('Disabled', { disabled: true }) + btn('Small 12px', { extra: 'height:28px;padding-top:0;padding-bottom:0;font-size:12px' })) +
    row('.btn-accent', btn('✨ Enhance', { kind: 'accent' }) + btn('＋ New collection', { kind: 'accent' }) + btn('Generate video', { kind: 'accent' })) +
    row('.btn-ghost / danger', btn('Cancel', { kind: 'ghost' }) + btn('✕', { kind: 'ghost', extra: 'padding:4px 8px' }) + btn('Delete', { kind: 'danger-active' })) +
    row('.chip', chip('flux.1-dev') + chip(`<span style="color:${T.faint}">steps</span> 28`) + chip('rim-light', `color:${T.emberSoft};border-color:${mix(T.ember, 30)}`) + chip('NEW', `font-size:10.5px;color:${T.ember};border-color:${mix(T.ember, 50)};background:${mix(T.ember, 10)};font-weight:600`) + chip('grid', `border-color:${T.ember};color:${T.fg}`) + chip('browser', 'font-size:10px')) +
    row('.input / select', `<span style="width:240px">${input('paste API key to connect', { placeholder: true, mono: true })}</span>` + select('All platforms') + select('Target model…', { small: false })) +
    row('.label', label('Prompt', 'margin-bottom:0') + label('Model &amp; parameters', 'margin-bottom:0')) +
    row('Toggle', toggle(true, 'On') + toggle(false, 'Off')) +
    row('ConnBadge', connBadge('connected') + connBadge('error') + connBadge('not_configured') + connBadge('offline')) +
    row('StatusDot', statusDot('ok', 'ok') + statusDot('experimental', 'experimental') + statusDot('error', 'error') + statusDot('off', 'needs setup')) +
    row('Filter toggle', `<button style="display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:${R.el};border:1px solid ${T.line};background:${T.panel};color:${T.fg};font-size:12.5px;font-weight:500">★ Favorites</button><button style="display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:${R.el};border:1px solid ${mix(T.ember, 70)};background:${mix(T.ember, 10)};color:${T.ember};font-size:12.5px;font-weight:500">★ Favorites</button>`)
  const mapping = [
    ['Tweak chip', 'Code it maps to'],
    ['accent', 'tailwind.config.ts → colors.ember (ember-soft = accent lightened 20%)'],
    ['ink · panel · well · line', 'tailwind.config.ts → colors.ink / panel / well / line'],
    ['fg · mute · faint', 'tailwind.config.ts → colors.fg / mute / faint'],
    ['card radius', 'tailwind.config.ts → borderRadius.card (used by .card)'],
    ['element radius', 'tailwind.config.ts → borderRadius.el (buttons, inputs, thumbs); chip = 60% of it'],
    ['display font', 'tailwind.config.ts → fontFamily.display + the @fontsource import in src/styles.css'],
  ].map(([a, b], i) => `<div style="display:grid;grid-template-columns:180px minmax(0, 1fr);gap:16px;padding:6px 0;border-bottom:1px solid ${T.line};font-size:${i ? 12.5 : 11}px;${i ? '' : `color:${T.faint};font-family:${F.mono}`}"><span style="${i ? 'font-weight:500' : ''}">${a}</span><span style="${i ? `font-family:${F.mono};font-size:11.5px;color:${T.mute}` : ''}">${b}</span></div>`).join('')
  const body = `<div style="padding:32px;display:flex;flex-direction:column;gap:16px">
    <div><h1 style="margin:0;font-family:${F.display};font-weight:500;font-size:19px;line-height:1.625">PromptForge design tokens</h1><p style="margin:0;font-size:12.5px;color:${T.faint}">Source of truth: frontend/tailwind.config.ts (colors, radii, fonts) and frontend/src/styles.css (.btn .chip .card .input .label). Dark-first: media is the hero, chrome stays quiet.</p></div>
    ${block('Colors', `<div style="display:flex;flex-wrap:wrap;gap:16px">${colors}</div>`)}
    <div style="display:grid;grid-template-columns:minmax(0, 1fr) 360px;gap:16px">${block('Type ramp — display font (default Space Grotesk) · Inter body · JetBrains Mono chips', type)}${block('Radii', `<div style="display:flex;flex-direction:column;gap:12px">${radii}</div><p style="margin:16px 0 0;font-size:12px;color:${T.faint}">Transitions 160ms · header 48px · controls 32px (filters) / 28px (card actions) · gallery gap 12px · page gutter 20px (12px on phones)</p>`)}</div>
    ${block('Components (styles.css @layer components + Primitives.tsx)', components)}
    ${block('How the tweak chips map to the code', mapping)}
  </div>`
  return document({ title: 'Design tokens', width: 1200, height: 1940, body })
}
