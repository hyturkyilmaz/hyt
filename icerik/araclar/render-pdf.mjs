// Kullanım: node icerik/araclar/render-pdf.mjs <sayfa.html> <cikti.pdf> [onizleme.png]
// HTML'i A4 PDF'e (ve isteğe bağlı PNG önizlemeye) çevirir.
import { execSync } from 'node:child_process';
import { resolve } from 'node:path';
const pw = await import('playwright').catch(() =>
  import(execSync('npm root -g').toString().trim() + '/playwright/index.js'));
const chromium = pw.chromium ?? pw.default.chromium;

const [, , htmlPath, pdfPath, pngPath] = process.argv;
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage();
await page.goto('file://' + resolve(htmlPath));
await page.evaluate(() => document.fonts.ready);
await page.pdf({ path: pdfPath, format: 'A4', printBackground: true, preferCSSPageSize: true });
if (pngPath) {
  await page.setViewportSize({ width: 794, height: 1123 });
  await page.screenshot({ path: pngPath, fullPage: true });
}
await browser.close();
console.log(pdfPath);
