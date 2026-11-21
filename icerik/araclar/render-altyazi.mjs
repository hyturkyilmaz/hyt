// Kullanım: node icerik/araclar/render-altyazi.mjs <is.json>
// is.json: [{ "text": "...", "out": "/yol/a.png", "accent": "#f29900" }, ...]
// Her metni şeffaf zeminli PNG altyazı kutusuna çevirir (genişlik 1080).
import { execSync } from 'node:child_process';
// playwright yerelde yoksa global kurulumdan yükle
const pw = await import('playwright').catch(() =>
  import(execSync('npm root -g').toString().trim() + '/playwright/index.js'));
const chromium = pw.chromium ?? pw.default.chromium;
import { readFileSync } from 'node:fs';

const jobs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage({ viewport: { width: 1080, height: 400 }, deviceScaleFactor: 1 });

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
for (const j of jobs) {
  // Büyük harfli anahtar kelimeler (AJAN gibi) vurgu rengini alır
  const html = esc(j.text).replace(/\b([A-ZÇĞİÖŞÜ]{3,})\b/g, `<b style="color:${j.accent || '#f29900'}">$1</b>`);
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;background:transparent;font-family:Inter,sans-serif}
    .wrap{width:1080px;display:flex;justify-content:center;align-items:flex-end;height:400px}
    .cap{max-width:920px;background:rgba(17,24,39,.92);color:#fff;font-size:44px;line-height:1.3;font-weight:700;
      padding:22px 34px;border-radius:24px;text-align:center;letter-spacing:-.3px;box-shadow:0 10px 30px rgba(0,0,0,.25)}
  </style></head><body><div class="wrap"><div class="cap">${html}</div></div></body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: j.out, omitBackground: true });
}
await browser.close();
console.log(jobs.length, 'altyazı');
