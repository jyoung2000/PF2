import type { Config } from 'tailwindcss'

// Design tokens (the ONLY place colors/radius/fonts are defined — no ad-hoc
// hex in components). Dark-first: media is the hero, chrome stays quiet.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0E0F12',        // page ground (deep neutral, not pure black)
        panel: '#15171C',      // raised surfaces (cards, drawer, header)
        well: '#1C1F26',       // inputs, chips, sunken areas
        line: '#272B33',       // hairline borders
        fg: '#E9EBEE',         // primary text
        mute: '#9BA3AF',       // secondary text
        faint: '#6B7280',      // tertiary text
        ember: '#FF6A3D',      // the one accent — interactive/selected only
        'ember-soft': '#FF8A65',
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        card: '14px',
        el: '10px',
        chip: '6px',
      },
      transitionDuration: { fast: '160ms' },
      maxWidth: { measure: '68ch' },
    },
  },
  plugins: [],
} satisfies Config
