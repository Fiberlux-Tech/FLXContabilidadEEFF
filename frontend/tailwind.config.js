/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Sidebar / chrome
        nav: {
          DEFAULT: '#0f172a',   // slate-900
          hover: '#1e293b',     // slate-800
          active: '#334155',    // slate-700
          border: '#334155',
          muted: '#94a3b8',     // slate-400
        },
        // Table header
        thead: {
          DEFAULT: '#1e293b',   // slate-800
        },
        // Accent
        accent: {
          DEFAULT: '#3b82f6',   // blue-500
          light: '#eff6ff',     // blue-50
          hover: '#dbeafe',     // blue-100
          ring: '#60a5fa',      // blue-400
        },
        // Status
        negative: '#dc2626',    // red-600
        positive: '#16a34a',    // green-600
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],  // 10px
      },
      boxShadow: {
        'sticky': '4px 0 6px -2px rgba(0,0,0,0.08)',
      },
    },
  },
  plugins: [],
}
