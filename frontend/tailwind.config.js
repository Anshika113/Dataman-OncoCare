/** @type {import('tailwindcss').Config} */
const shades = ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900', '950']

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  safelist: [
    // guarantee every custom color shade is generated, even when a color is
    // only referenced inside @layer base / component classes (which JIT can't see)
    ...shades.flatMap((s) => [
      `bg-brand-${s}`, `text-brand-${s}`, `border-brand-${s}`, `ring-brand-${s}`,
      `from-brand-${s}`, `to-brand-${s}`, `via-brand-${s}`, `shadow-brand-${s}`,
      `bg-ink-${s}`, `text-ink-${s}`, `border-ink-${s}`, `ring-ink-${s}`,
      `from-ink-${s}`, `to-ink-${s}`, `placeholder-ink-${s}`,
    ]),
  ],
  theme: {
    extend: {
      colors: {
        // Petrol — desaturated blue-green. Calm enough to sit behind a
        // nine-hour shift, and quiet enough that emerald / amber / rose keep
        // meaning something when they appear.
        brand: {
          50: '#f1f7f8', 100: '#dcecef', 200: '#b9d8dd', 300: '#8bbdc6',
          400: '#559ca9', 500: '#37808d', 600: '#2a6775', 700: '#265461',
          800: '#254651', 900: '#223b44', 950: '#11242b',
        },
        // The mid-range carries nearly every word in this app: 112 uses of
        // text-ink-400 and 91 of text-ink-500. At the original values 400 sat
        // at 3.66:1 on white — under WCAG AA — and the whole interface read
        // grey. The scale has been pulled toward the ink end twice; these are
        // the contrast ratios on white now:
        //   300 3.04 (placeholders only) · 400 6.32 · 500 9.33 · 600 11.24
        //   700 13.05 · 800 15.17 · 900 17.27
        // Each step is still darker than the last, so the ramp works as a
        // ramp; it just starts much closer to black than it used to.
        ink: {
          50: '#f6f7f9', 100: '#eceef2', 200: '#d3d8e0', 300: '#8b94a8',
          400: '#566074', 500: '#3f4757', 600: '#343b49', 700: '#2b313d',
          800: '#212630', 900: '#171b22', 950: '#0e1116',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.1)',
        pop: '0 10px 30px -8px rgba(16,24,40,.25)',
        glow: '0 0 0 1px rgba(55,128,141,.15), 0 20px 40px -12px rgba(42,103,117,.35)',
      },
      keyframes: {
        fadein: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        slidein: { '0%': { opacity: '0', transform: 'translateX(16px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        // centered modal entrance: fade + scale up from just below 100%
        pop: { '0%': { opacity: '0', transform: 'scale(.96) translateY(8px)' }, '100%': { opacity: '1', transform: 'scale(1) translateY(0)' } },
      },
      animation: {
        fadein: 'fadein .35s ease-out',
        slidein: 'slidein .3s ease-out',
        pop: 'pop .25s cubic-bezier(.2,.9,.3,1)',
      },
    },
  },
  plugins: [],
}
