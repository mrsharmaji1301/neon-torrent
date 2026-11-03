// Tailwind config for the phone page (colours and type scale from the Stitch "NEON File Share" designs).
// Fonts are system stacks: the page works offline and ships no font files.
const path = require('path');
const sans = ['system-ui', '-apple-system', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif'];
const mono = ['ui-monospace', '"SF Mono"', '"Roboto Mono"', 'Menlo', 'Consolas', 'monospace'];

module.exports = {
  darkMode: 'class',
  content: [path.join(__dirname, 'index.html'), path.join(__dirname, 'app.js')],
  theme: {
    extend: {
      colors: {
        'on-surface': '#dee2f3', 'surface-container-low': '#161c27', 'surface-container': '#1a202b',
        secondary: '#faabff', 'surface-container-highest': '#2f3541', background: '#0e131f',
        'on-surface-variant': '#bbc9cd', 'surface-container-lowest': '#090e19', 'tertiary-container': '#00dd71',
        primary: '#8aebff', 'primary-container': '#22d3ee', 'primary-fixed': '#a2eeff', outline: '#859397',
        'surface-container-high': '#252a36', 'secondary-container': '#bd06da', tertiary: '#39fb88',
        'outline-variant': '#3c494c', surface: '#0e131f', error: '#ffb4ab',
      },
      spacing: { 'space-lg': '1.25rem', 'space-sm': '0.5rem', gutter: '1rem', margin: '1rem', 'space-xs': '0.25rem',
        'space-xl': '2rem', 'space-md': '0.875rem' },
      fontFamily: { 'headline-sm': sans, 'label-md': mono, 'label-sm': mono, 'body-sm': sans, 'body-md': sans },
      fontSize: {
        'label-md': ['11px', { lineHeight: '14px', letterSpacing: '0.06em', fontWeight: '500' }],
        'body-sm': ['12px', { lineHeight: '16px', fontWeight: '400' }],
        'label-sm': ['10px', { lineHeight: '12px', letterSpacing: '0.08em', fontWeight: '400' }],
        'body-md': ['14px', { lineHeight: '20px', fontWeight: '400' }],
        'headline-sm': ['20px', { lineHeight: '26px', letterSpacing: '-0.01em', fontWeight: '600' }],
      },
    },
  },
  plugins: [],
};
