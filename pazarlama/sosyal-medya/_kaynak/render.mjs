// Sosyal medya karusel üretici.
// Kullanım:
//   node render.mjs                -> tüm postları 1080x1350 (4:5) PNG olarak üretir
//   node render.mjs --dikey 02     -> id'si "02" ile başlayan postu 1080x1920 (9:16) üretir (video için)
// Çıktı: ../<post-id>/slayt-N.png  (dikey için ../<post-id>/dikey/slayt-N.png)
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Playwright global kurulu olabilir; ESM import NODE_PATH'i görmediği için require ile yüklenir
const { chromium } = createRequire(import.meta.url)('playwright');
const BURASI = path.dirname(fileURLToPath(import.meta.url));
const veri = JSON.parse(fs.readFileSync(path.join(BURASI, 'posts.json'), 'utf8'));

const argDikey = process.argv.indexOf('--dikey');
const DIKEY = argDikey !== -1;
const FILTRE = DIKEY ? process.argv[argDikey + 1] : null;
const GEN = 1080;
const YUK = DIKEY ? 1920 : 1350;

// HTML'e girecek metinleri kaçışla (XSS/kırık işaretleme önlemi)
const kac = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Avatar: dosya varsa gömülür, yoksa baş harfli yer tutucu çizilir
function avatarHtml(imza) {
  const adaylar = [imza.avatar, imza.avatar.replace(/\.jpe?g$/i, '.png')].map((a) => path.resolve(BURASI, a));
  const yol = adaylar.find((a) => fs.existsSync(a));
  if (yol) {
    const uzanti = path.extname(yol).slice(1).toLowerCase().replace('jpg', 'jpeg');
    const b64 = fs.readFileSync(yol).toString('base64');
    return `<img class="avatar" src="data:image/${uzanti};base64,${b64}" alt="">`;
  }
  return `<div class="avatar yer-tutucu">${kac(imza.bas_harfler)}</div>`;
}

const CSS = `
:root{--zemin:#0F1B2D;--zemin2:#16263D;--metin:#F4F1EA;--ikincil:#A9B8CC;--vurgu:#F2B544;--cizgi:#2A3D58}
*{box-sizing:border-box;margin:0;padding:0}
body{width:${GEN}px;height:${YUK}px;background:var(--zemin);color:var(--metin);
  font-family:'Inter','DejaVu Sans',sans-serif;-webkit-font-smoothing:antialiased}
.slayt{position:relative;width:100%;height:100%;padding:96px 88px 88px;display:flex;flex-direction:column;
  background:radial-gradient(1200px 700px at 100% 0%,var(--zemin2) 0%,var(--zemin) 60%)}
.ust{display:flex;justify-content:space-between;align-items:center;font-size:24px;letter-spacing:.14em;
  color:var(--ikincil);font-weight:600}
.ust .sayac{letter-spacing:.05em;font-variant-numeric:tabular-nums}
.govde{flex:1;display:flex;flex-direction:column;justify-content:center;gap:44px}
.serit{width:96px;height:8px;background:var(--vurgu);border-radius:4px}
h1{font-size:${DIKEY ? 92 : 84}px;line-height:1.06;font-weight:800;letter-spacing:-.025em}
.vurgu{color:var(--vurgu);font-size:${DIKEY ? 60 : 54}px;line-height:1.15;font-weight:700;letter-spacing:-.015em}
.alt{font-size:34px;line-height:1.45;color:var(--ikincil);max-width:860px}
h2{font-size:${DIKEY ? 72 : 66}px;line-height:1.1;font-weight:800;letter-spacing:-.02em}
ul{list-style:none;display:flex;flex-direction:column;gap:${DIKEY ? 38 : 30}px}
li{position:relative;padding-left:48px;font-size:${DIKEY ? 38 : 34}px;line-height:1.42}
li::before{content:"";position:absolute;left:0;top:.55em;width:20px;height:20px;border-radius:50%;
  border:4px solid var(--vurgu)}
.alt-bilgi{display:flex;justify-content:space-between;align-items:flex-end;gap:32px;border-top:2px solid var(--cizgi);
  padding-top:28px;font-size:22px;color:var(--ikincil)}
.alt-bilgi .kaynak{max-width:640px;line-height:1.4}
.alt-bilgi .isim{font-weight:600;color:var(--metin);white-space:nowrap}
.kaydir{color:var(--vurgu);font-weight:700}
.cta .govde{align-items:center;text-align:center;gap:40px}
.avatar{width:300px;height:300px;border-radius:50%;object-fit:cover;border:8px solid var(--vurgu)}
.yer-tutucu{display:flex;align-items:center;justify-content:center;background:var(--zemin2);
  font-size:96px;font-weight:800;color:var(--vurgu);letter-spacing:.04em}
.cta .ozet{font-size:${DIKEY ? 50 : 46}px;line-height:1.25;font-weight:700;max-width:880px;letter-spacing:-.01em}
.cta .ad{font-size:46px;font-weight:800}
.cta .unvan{font-size:28px;color:var(--ikincil);letter-spacing:.06em;margin-top:-24px}
.cta .eylem{font-size:34px;line-height:1.4;background:var(--vurgu);color:var(--zemin);font-weight:700;
  padding:26px 44px;border-radius:20px;max-width:900px}
`;

function slaytHtml(post, s, i, toplam, imza) {
  const sayac = `${i + 1}/${toplam}`;
  const ust = `<div class="ust"><span>${kac(post.etiket)}</span><span class="sayac">${sayac}</span></div>`;
  let govde = '';
  let alt = '';
  if (s.tip === 'kapak') {
    govde = `<div class="serit"></div><h1>${kac(s.baslik)}</h1><div class="vurgu">${kac(s.vurgu)}</div>
      <p class="alt">${kac(s.metin)}</p>`;
    alt = `<div class="alt-bilgi"><span class="isim">${kac(imza.isim)}</span><span class="kaydir">Kaydırın →</span></div>`;
  } else if (s.tip === 'icerik') {
    govde = `<h2>${kac(s.baslik)}</h2><ul>${s.maddeler.map((m) => `<li>${kac(m)}</li>`).join('')}</ul>`;
    alt = `<div class="alt-bilgi"><span class="kaynak">Kaynak: ${kac(s.kaynak)}</span><span class="isim">${kac(imza.isim)}</span></div>`;
  } else if (s.tip === 'cta') {
    govde = `<p class="ozet">${kac(s.ozet)}</p>${avatarHtml(imza)}
      <div class="ad">${kac(imza.isim)}</div><div class="unvan">${kac(imza.unvan)}</div>
      <div class="eylem">${kac(imza.cta)}</div>`;
  } else {
    throw new Error(`Bilinmeyen slayt tipi: ${s.tip} (${post.id})`);
  }
  return `<!doctype html><html lang="tr"><head><meta charset="utf-8"><style>${CSS}</style></head>
    <body><div class="slayt ${s.tip}">${ust}<div class="govde">${govde}</div>${alt}</div></body></html>`;
}

// Kalıcı kural: her post CTA + avatar slaytıyla bitmeli
function dogrula(post) {
  const son = post.slaytlar.at(-1);
  if (!son || son.tip !== 'cta') throw new Error(`${post.id}: son slayt CTA olmalı`);
  if (post.slaytlar.length < 3 || post.slaytlar.length > 6) throw new Error(`${post.id}: 3-6 slayt olmalı`);
}

const tarayici = await chromium.launch();
const sayfa = await tarayici.newPage({ viewport: { width: GEN, height: YUK }, deviceScaleFactor: 1 });
let adet = 0;
for (const post of veri.postlar) {
  if (FILTRE && !post.id.startsWith(FILTRE)) continue;
  dogrula(post);
  const hedef = path.join(BURASI, '..', post.id, DIKEY ? 'dikey' : '');
  fs.mkdirSync(hedef, { recursive: true });
  for (const [i, s] of post.slaytlar.entries()) {
    await sayfa.setContent(slaytHtml(post, s, i, post.slaytlar.length, veri.imza), { waitUntil: 'load' });
    await sayfa.evaluate(() => document.fonts.ready);
    await sayfa.screenshot({ path: path.join(hedef, `slayt-${i + 1}.png`) });
    adet++;
  }
}
await tarayici.close();
console.log(`${adet} slayt üretildi (${GEN}x${YUK}).`);
