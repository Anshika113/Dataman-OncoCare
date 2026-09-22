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
        brand: {
          50: '#eef4ff', 100: '#dbe6fe', 200: '#bfd3fe', 300: '#93b4fd',
          400: '#608afa', 500: '#3b62f6', 600: '#2543eb', 700: '#1d33d8',
          800: '#1e2daf', 900: '#1e2b8a', 950: '#141a4a',
        },
        ink: {
          50: '#f6f7f9', 100: '#eceef2', 200: '#d3d8e0', 300: '#adb6c6',
          400: '#7b869c', 500: '#5a6579', 600: '#454f63', 700: '#394153',
          800: '#2b3140', 900: '#1c202b', 950: '#12151d',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,.06), 0 1px 3px rgba(16,24,40,.1)',
        pop: '0 10px 30px -8px rgba(16,24,40,.25)',
        glow: '0 0 0 1px rgba(59,98,246,.15), 0 20px 40px -12px rgba(37,67,235,.35)',
      },
      keyframes: {
        fadein: { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        slidein: { '0%': { opacity: '0', transform: 'translateX(16px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
      },
      animation: {
        fadein: 'fadein .35s ease-out',
        slidein: 'slidein .3s ease-out',
      },
    },
  },
  plugins: [],
}
