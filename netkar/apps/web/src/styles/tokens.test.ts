import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// tokens.css içindeki renk çiftlerinin WCAG 2.2 AA kontrastını doğrular.
const css = readFileSync(join(__dirname, 'tokens.css'), 'utf8');

function extractBlock(startMarker: string): Record<string, string> {
  const start = css.indexOf(startMarker);
  if (start === -1) throw new Error(`Blok bulunamadı: ${startMarker}`);
  const open = css.indexOf('{', start);
  const close = css.indexOf('}', open);
  const body = css.slice(open + 1, close);
  const vars: Record<string, string> = {};
  for (const match of body.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6});/g)) {
    vars[match[1] as string] = match[2] as string;
  }
  return vars;
}

const light = extractBlock(':root {');
const dark = extractBlock(":root[data-theme='dark']");
// Sistem tercihi bloğu ile elle seçilen koyu tema aynı değerleri taşımalı
const darkMedia = extractBlock(":root:not([data-theme='light'])");

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * (channels[0] as number) +
    0.7152 * (channels[1] as number) +
    0.0722 * (channels[2] as number)
  );
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

// [ön plan, arka plan, en az oran]
const TEXT_PAIRS: [string, string, number][] = [
  ['foreground', 'background', 4.5],
  ['foreground', 'surface', 4.5],
  ['foreground', 'surface-muted', 4.5],
  ['muted-foreground', 'background', 4.5],
  ['muted-foreground', 'surface', 4.5],
  ['muted-foreground', 'surface-muted', 4.5],
  ['primary-foreground', 'primary', 4.5],
  ['primary-foreground', 'primary-hover', 4.5],
  ['primary', 'background', 4.5],
  ['primary', 'surface', 4.5],
  ['primary', 'info-soft', 4.5],
  ['profit', 'background', 4.5],
  ['profit', 'surface', 4.5],
  ['profit', 'profit-soft', 4.5],
  ['loss', 'background', 4.5],
  ['loss', 'surface', 4.5],
  ['loss', 'loss-soft', 4.5],
  ['warning', 'background', 4.5],
  ['warning', 'surface', 4.5],
  ['warning', 'warning-soft', 4.5],
];

// Metin dışı: girdi kenarlığı ve odak halkası (WCAG 1.4.11, en az 3:1)
const UI_PAIRS: [string, string, number][] = [
  ['input-border', 'surface', 3],
  ['input-border', 'background', 3],
  ['ring', 'background', 3],
  ['ring', 'surface', 3],
];

describe.each([
  ['açık tema', light],
  ['koyu tema', dark],
])('%s kontrastı', (_name, tokens) => {
  it.each(TEXT_PAIRS)('%s / %s en az %s:1', (fg, bg, min) => {
    const ratio = contrast(tokens[fg] as string, tokens[bg] as string);
    expect(
      ratio,
      `${fg} ${tokens[fg]} / ${bg} ${tokens[bg]} = ${ratio.toFixed(2)}`,
    ).toBeGreaterThanOrEqual(min);
  });

  it.each(UI_PAIRS)('%s / %s en az %s:1', (fg, bg, min) => {
    const ratio = contrast(tokens[fg] as string, tokens[bg] as string);
    expect(ratio, `${fg} / ${bg} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(min);
  });
});

describe('koyu tema tutarlılığı', () => {
  it('sistem tercihi bloğu ile data-theme="dark" bloğu aynı renkleri taşır', () => {
    expect(darkMedia).toEqual(dark);
  });
});
