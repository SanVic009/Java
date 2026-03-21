/** @type {import('tailwindcss').Config} */
import colors from 'tailwindcss/colors';

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        accent: '#10b981', // Emerald 500
        'accent-dark': '#059669', // Emerald 600
        'accent-soft': '#ecfdf5', // Emerald 50
        surface: '#ffffff',
        base: '#0f172a', // Slate 900 for text
      },
      fontFamily: {
        sans: ['"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      backgroundImage: {
        'grid-pattern': "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40' viewBox='0 0 40 40'%3E%3Cpath d='M0 40 L40 40 L40 0' fill='none' stroke='%23e2e8f0' stroke-width='1'/%3E%3C/svg%3E\")",
      }
    },
  },
  plugins: [],
}
