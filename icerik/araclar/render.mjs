// Kullanım: node icerik/araclar/render.mjs <slaytlar.html> <cikti-klasoru>
// Her <section class="slide"> öğesini 1080x1350 PNG olarak kaydeder.
import { execSync } from 'node:child_process';
// playwright yerelde yoksa global kurulumdan yükle
const pw = await import('playwright').catch(() =>
  import(execSync('npm root -g').toString().trim() + '/playwright/index.js'));
const chromium = pw.chromium ?? pw.default.chromium;
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';

const [, , htmlPath, outDir] = process.argv;
if (!htmlPath || !outDir) {
  console.error('Kullanım: node render.mjs <slaytlar.html> <cikti-klasoru>');
  process.exit(1);
}
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 1 });
await page.goto('file://' + resolve(htmlPath));
await page.evaluate(() => document.fonts.ready);

const slides = await page.$$('section.slide');
for (const [i, el] of slides.entries()) {
  const file = resolve(outDir, `slayt-${String(i + 1).padStart(2, '0')}.png`);
  await el.screenshot({ path: file });
  console.log(file);
}
await browser.close();
