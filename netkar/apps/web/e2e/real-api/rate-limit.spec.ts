import { expect, test, type APIRequestContext } from '@playwright/test';
import { randomBytes } from 'node:crypto';

// Denetim Y-01 (ADR-0002): gerçek zincir tarayıcı/istemci -> Next.js (middleware + rewrites) -> API.
// Web CLIENT_IP_SOURCE=cf-connecting-ip ile çalışır (playwright.real-api.config.ts); bu testteki
// istemci "Cloudflare" rolündedir ve CF-Connecting-IP ile gerçek istemciyi belirtir. Sahte
// X-Forwarded-For / X-Real-IP başlıkları (istemci yazabilir) kovayı değiştirememeli.
// API'nin IP sınırı: giriş için 30 / 15 dk (varsayılan). Her istemci benzersiz TEST-NET-3 adresi
// kullanır; böylece diğer e2e akışlarının (loopback kovası) sayaçlarına dokunulmaz.
const LOGIN_IP_LIMIT = 30;
const run = randomBytes(2).readUInt16BE(0) % 200;

function clientAddress(slot: number): string {
  return `203.0.113.${(run + slot) % 250 || 1}`;
}

async function csrfHeaders(request: APIRequestContext) {
  const res = await request.get('/api/v1/auth/csrf');
  const token = ((await res.json()) as { csrf_token: string }).csrf_token;
  return { cookie: `__Host-nk_csrf=${token}`, 'x-csrf-token': token };
}

/** Var olmayan e-postayla giriş denemesi: 401 (sayaç artar) ya da IP sınırı aşıldıysa 429. */
async function attempt(
  request: APIRequestContext,
  csrf: Record<string, string>,
  index: number,
  extra: Record<string, string>,
) {
  const res = await request.post('/api/v1/auth/login', {
    headers: { ...csrf, ...extra },
    data: { email: `yok-${randomBytes(6).toString('hex')}-${index}@ornek.com`, password: 'x' },
  });
  return res.status();
}

test('sahte X-Forwarded-For döndürerek IP sınırı aşılamaz', async ({ request }) => {
  const csrf = await csrfHeaders(request);
  const real = clientAddress(1);
  const codes: number[] = [];
  for (let i = 0; i < LOGIN_IP_LIMIT + 3; i++) {
    codes.push(
      await attempt(request, csrf, i, {
        'cf-connecting-ip': real,
        // İstemcinin yazdığı sahte zincir her istekte değişir; web bunları atmalı.
        'x-forwarded-for': `10.9.${i % 250}.${(i * 7) % 250}`,
        'x-real-ip': `10.8.${i % 250}.1`,
      }),
    );
  }
  expect(codes.slice(0, LOGIN_IP_LIMIT).every((c) => c === 401)).toBe(true);
  expect(codes.slice(LOGIN_IP_LIMIT)).toEqual([429, 429, 429]);
});

test('farklı gerçek istemciler birbirinin sınırını tüketmez', async ({ request }) => {
  const csrf = await csrfHeaders(request);
  const attacker = clientAddress(60);
  const victim = clientAddress(61);
  let last = 0;
  for (let i = 0; i < LOGIN_IP_LIMIT + 1; i++) {
    last = await attempt(request, csrf, i, { 'cf-connecting-ip': attacker });
  }
  expect(last).toBe(429);
  // Başka bir gerçek istemci aynı vekil/IP havuzunu paylaşmaz
  expect(await attempt(request, csrf, 0, { 'cf-connecting-ip': victim })).toBe(401);
  // Saldırganın sahte XFF ile kurbanın kovasına yazması da mümkün değil: kurban sayacı 1'de kalır
  for (let i = 0; i < 5; i++) {
    await attempt(request, csrf, i, { 'cf-connecting-ip': attacker, 'x-forwarded-for': victim });
  }
  expect(await attempt(request, csrf, 1, { 'cf-connecting-ip': victim })).toBe(401);
});

test('CF-Connecting-IP olmayan istek sahte XFF ile yeni kova açamaz', async ({ request }) => {
  const csrf = await csrfHeaders(request);
  const codes: number[] = [];
  for (let i = 0; i < LOGIN_IP_LIMIT + 3; i++) {
    codes.push(await attempt(request, csrf, i, { 'x-forwarded-for': `10.7.${i % 250}.9` }));
  }
  // İstemci IP'si belirlenemeyince API vekilin (web) adresine düşer: tek kova, sınır dolar.
  // (Diğer testlerin loopback sayaçları da bu kovada olabilir; en az bir 429 beklenir.)
  expect(codes.at(-1)).toBe(429);
});
