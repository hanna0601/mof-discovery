/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#090B10',
        surface: '#10151D',
        card:    '#151B24',
        border:  '#253040',
        muted:   '#8C98A8',
        primary: { DEFAULT: '#0EA5A4', hover: '#0D8F8E', light: '#0EA5A422' },
        success: { DEFAULT: '#22C55E', light: '#22C55E20' },
        warning: { DEFAULT: '#F59E0B', light: '#F59E0B20' },
        danger:  { DEFAULT: '#EF4444', light: '#EF444420' },
        info:    { DEFAULT: '#60A5FA', light: '#60A5FA20' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow':  'spin 2s linear infinite',
      },
    },
  },
  plugins: [],
}
