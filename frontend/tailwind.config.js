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
          DEFAULT: '#F3F2EF',
          hover: '#E9E8E4',
          active: '#FFEFE5',
          border: '#E0DFDB',
          muted: '#808080',
          text: '#333333',
        },
        // Table header
        thead: {
          DEFAULT: '#FAFAFA',
        },
        // Accent (warm red)
        accent: {
          DEFAULT: '#D1453B',
          light: '#FFEFE5',
          hover: '#B8352D',
          ring: '#D1453B',
        },
        // Status
        negative: '#D1453B',
        positive: '#058527',
        // Surfaces
        surface: {
          DEFAULT: '#FFFFFF',
          alt: '#FAFAFA',
        },
        // Semantic borders
        border: {
          DEFAULT: '#E8E8E8',
          light: '#F0F0F0',
        },
        // Semantic text hierarchy
        txt: {
          DEFAULT: '#202020',
          secondary: '#666666',
          muted: '#999999',
          faint: '#CCCCCC',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        serif: ["'Playfair Display'", 'Georgia', "'Times New Roman'", 'serif'],
        mono: ["'SF Mono'", "'Fira Code'", "'Cascadia Code'", 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],  // 10px
      },
      boxShadow: {
        'sticky': '4px 0 8px -3px rgba(0,0,0,0.04)',
      },
    },
  },
  plugins: [],
}
