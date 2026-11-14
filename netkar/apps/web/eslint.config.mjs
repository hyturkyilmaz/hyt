import { FlatCompat } from '@eslint/eslintrc';
import security from 'eslint-plugin-security';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'test-results/**',
      'playwright-report/**',
      'next-env.d.ts',
    ],
  },
  // next: core-web-vitals, typescript ve jsx-a11y kuralları (eslint-config-next içinde gelir)
  ...compat.extends('next/core-web-vitals', 'next/typescript', 'plugin:jsx-a11y/recommended'),
  security.configs.recommended,
  {
    rules: {
      // Dizin erişimi kuralı tip güvenli koddaki sabit anahtarlarda sürekli yanlış alarm veriyor.
      'security/detect-object-injection': 'off',
      // Kullanıcı girdisi HTML olarak yazılmaz; tek istisna JsonLd bileşeninde açıkça kapatılır.
      'react/no-danger': 'error',
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // Tailwind `list-none` Safari/VoiceOver'da liste anlamını düşürür (denetim SU-09): ul/ol için açık
      // role="list" bilerek yazılır.
      'jsx-a11y/no-redundant-roles': ['error', { ul: ['list'], ol: ['list'] }],
    },
  },
  {
    files: ['**/*.test.ts', '**/*.test.tsx', 'e2e/**', 'playwright.config.ts', 'playwright.real-api.config.ts'],
    rules: { 'security/detect-non-literal-fs-filename': 'off', 'no-console': 'off' },
  },
];

export default eslintConfig;
