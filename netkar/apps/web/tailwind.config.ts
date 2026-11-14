import type { Config } from 'tailwindcss';

// Renkler ve ölçüler src/styles/tokens.css içindeki değişkenlerden gelir.
const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'var(--background)',
        surface: 'var(--surface)',
        'surface-muted': 'var(--surface-muted)',
        foreground: 'var(--foreground)',
        'muted-foreground': 'var(--muted-foreground)',
        border: 'var(--border)',
        'input-border': 'var(--input-border)',
        ring: 'var(--ring)',
        primary: {
          DEFAULT: 'var(--primary)',
          hover: 'var(--primary-hover)',
          foreground: 'var(--primary-foreground)',
        },
        profit: { DEFAULT: 'var(--profit)', soft: 'var(--profit-soft)' },
        loss: { DEFAULT: 'var(--loss)', soft: 'var(--loss-soft)' },
        warning: { DEFAULT: 'var(--warning)', soft: 'var(--warning-soft)' },
        info: { DEFAULT: 'var(--info)', soft: 'var(--info-soft)' },
      },
      fontFamily: { sans: ['var(--font-sans)', 'system-ui', 'sans-serif'] },
      fontSize: {
        xs: ['var(--text-xs)', { lineHeight: '1.4' }],
        sm: ['var(--text-sm)', { lineHeight: '1.5' }],
        base: ['var(--text-base)', { lineHeight: 'var(--leading-normal)' }],
        lg: ['var(--text-lg)', { lineHeight: 'var(--leading-snug)' }],
        xl: ['var(--text-xl)', { lineHeight: 'var(--leading-snug)' }],
        '2xl': ['var(--text-2xl)', { lineHeight: 'var(--leading-tight)' }],
        '3xl': ['var(--text-3xl)', { lineHeight: 'var(--leading-tight)' }],
        '4xl': ['var(--text-4xl)', { lineHeight: 'var(--leading-tight)' }],
        '5xl': ['var(--text-5xl)', { lineHeight: '1.1' }],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        full: 'var(--radius-full)',
      },
      boxShadow: { sm: 'var(--shadow-sm)', md: 'var(--shadow-md)' },
      spacing: { touch: 'var(--touch-target)' },
      minHeight: { touch: 'var(--touch-target)' },
      minWidth: { touch: 'var(--touch-target)' },
      height: { touch: 'var(--touch-target)', 'bottom-nav': 'var(--bottom-nav-height)' },
      width: { sidebar: 'var(--sidebar-width)' },
      maxWidth: { content: 'var(--content-max)' },
      padding: {
        sidebar: 'var(--sidebar-width)',
        gutter: 'var(--gutter)',
        'bottom-nav': 'var(--bottom-nav-height)',
      },
      keyframes: { shimmer: { '100%': { transform: 'translateX(100%)' } } },
    },
  },
  plugins: [],
};

export default config;
