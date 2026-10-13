// Kullanım: node icerik/araclar/render-media.mjs <slaytlar.html> <cikti-klasoru> [fps]
// data-duration taşıyan slaytları MP4'e, diğerlerini PNG'ye çevirir.
// Animasyonlar Web Animations API ile kare kare durdurulup çekilir; sonuç her seferinde aynıdır.
// Gerekli: playwright, ffmpeg.
import { chromium } from 'playwright';
import { resolve, join } from 'node:path';
import { mkdirSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const [, , htmlPath, outDir, fpsArg] = process.argv;
if (!htmlPath || !outDir) {
  console.error('Kullanım: node render-media.mjs <slaytlar.html> <cikti-klasoru> [fps]');
  process.exit(1);
}
const fps = Number(fpsArg || 30);
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}
);
const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 1 });
await page.goto('file://' + resolve(htmlPath));
await page.evaluate(() => document.fonts.ready);

const ids = await page.$$eval('section.slide', els => els.map(e => ({ id: e.id, d: Number(e.dataset.duration || 0) })));

for (const [i, { id, d }] of ids.entries()) {
  const el = await page.$('#' + id);
  const base = join(outDir, `slayt-${String(i + 1).padStart(2, '0')}`);

  // Statik kare: animasyonların bitmiş hali
  await page.evaluate(() => document.getAnimations().forEach(a => { a.pause(); a.currentTime = 30000; }));
  await el.screenshot({ path: base + '.png' });

  if (!d) { console.log(base + '.png'); continue; }

  const frames = base + '_frames';
  rmSync(frames, { recursive: true, force: true });
  mkdirSync(frames);
  const total = Math.round(d * fps);
  for (let f = 0; f < total; f++) {
    const t = (f / fps) * 1000;
    await page.evaluate(ms => document.getAnimations().forEach(a => { a.pause(); a.currentTime = ms; }), t);
    await el.screenshot({ path: join(frames, `${String(f).padStart(4, '0')}.png`) });
  }
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(fps), '-i', join(frames, '%04d.png'),
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-movflags', '+faststart', base + '.mp4']);
  rmSync(frames, { recursive: true, force: true });
  console.log(base + '.mp4');
}
await browser.close();
