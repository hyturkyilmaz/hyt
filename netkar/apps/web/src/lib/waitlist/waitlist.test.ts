import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { handleWaitlistRequest, type WaitlistDeps } from './handler';
import { createRateLimiter } from './rate-limit';
import { PRIVACY_NOTICE_VERSION } from './schema';
import { FileWaitlistSink, MemoryWaitlistSink, resolveSink } from './sink';
import { verifyTurnstile } from './turnstile';
import { validateWaitlistForm } from './validate';

const ORIGIN = 'https://netkar.example';

function makeDeps(overrides: Partial<WaitlistDeps> = {}) {
  const sink = new MemoryWaitlistSink();
  const deps: WaitlistDeps = {
    siteOrigin: ORIGIN,
    sink,
    turnstile: { enabled: false },
    limiter: createRateLimiter({ limit: 100, windowMs: 60_000 }),
    now: () => new Date('2026-11-07T10:00:00.000Z'),
    ...overrides,
  };
  return { deps, sink };
}

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request(`${ORIGIN}/api/bekleme-listesi`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: ORIGIN, ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

const valid = { email: 'Ornek@Magaza.com ', monthlyOrders: '100-1000', marketingConsent: false };

describe('bekleme listesi uç noktası', () => {
  it('geçerli kaydı alır, e-postayı küçük harfe çevirir, onay yoksa tarih yazmaz', async () => {
    const { deps, sink } = makeDeps();
    const response = await handleWaitlistRequest(post(valid), deps);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'ok' });
    expect(sink.entries()).toEqual([
      {
        email: 'ornek@magaza.com',
        storeCategory: null,
        monthlyOrders: '100-1000',
        marketingConsent: false,
        marketingConsentAt: null,
        privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
        createdAt: '2026-11-07T10:00:00.000Z',
      },
    ]);
  });

  it('ticari ileti onayı verildiyse onay zamanını ve kategoriyi saklar', async () => {
    const { deps, sink } = makeDeps();
    await handleWaitlistRequest(
      post({ ...valid, storeCategory: 'giyim', marketingConsent: true }),
      deps,
    );
    const [entry] = sink.entries();
    expect(entry?.marketingConsent).toBe(true);
    expect(entry?.marketingConsentAt).toBe('2026-11-07T10:00:00.000Z');
    expect(entry?.storeCategory).toBe('giyim');
  });

  it('aynı e-postayı tekrar gönderene aynı yanıtı verir ve ikinci kayıt açmaz', async () => {
    const { deps, sink } = makeDeps();
    const first = await handleWaitlistRequest(post(valid), deps);
    const second = await handleWaitlistRequest(post(valid), deps);
    expect(second.status).toBe(first.status);
    expect(await second.json()).toEqual(await first.json());
    expect(sink.entries()).toHaveLength(1);
  });

  it('geçersiz e-posta ve eksik sipariş aralığında 422 ve alan kodları döner', async () => {
    const { deps, sink } = makeDeps();
    const response = await handleWaitlistRequest(
      post({ email: 'gecersiz', monthlyOrders: 'x', marketingConsent: false }),
      deps,
    );
    expect(response.status).toBe(422);
    expect(response.headers.get('content-type')).toContain('application/problem+json');
    const body = (await response.json()) as { errors: { field: string }[] };
    expect(body.errors.map((e) => e.field).sort()).toEqual(['email', 'monthlyOrders']);
    expect(sink.entries()).toHaveLength(0);
  });

  it('onay alanı yoksa onay verilmiş sayılmaz: şema boolean ister', async () => {
    const { deps } = makeDeps();
    const response = await handleWaitlistRequest(
      post({ email: 'a@b.co', monthlyOrders: 'yok' }),
      deps,
    );
    expect(response.status).toBe(422);
  });

  it('başka kökenden gelen isteği reddeder (CSRF)', async () => {
    const { deps, sink } = makeDeps();
    const response = await handleWaitlistRequest(
      post(valid, { Origin: 'https://kotu.example' }),
      deps,
    );
    expect(response.status).toBe(403);
    expect(sink.entries()).toHaveLength(0);
  });

  it('Origin yoksa yalnız Sec-Fetch-Site: same-origin kabul edilir', async () => {
    const { deps } = makeDeps();
    const noOrigin = new Request(`${ORIGIN}/api/bekleme-listesi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(valid),
    });
    expect((await handleWaitlistRequest(noOrigin, deps)).status).toBe(403);
    const sameOrigin = new Request(`${ORIGIN}/api/bekleme-listesi`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-origin' },
      body: JSON.stringify(valid),
    });
    expect((await handleWaitlistRequest(sameOrigin, deps)).status).toBe(200);
  });

  it('JSON olmayan içerik türünü, bozuk JSON ve büyük gövdeyi reddeder', async () => {
    const { deps } = makeDeps();
    expect(
      (await handleWaitlistRequest(post('a=b', { 'Content-Type': 'text/plain' }), deps)).status,
    ).toBe(415);
    expect((await handleWaitlistRequest(post('{bozuk'), deps)).status).toBe(400);
    const big = JSON.stringify({ ...valid, website: '', turnstileToken: 'x'.repeat(5000) });
    expect((await handleWaitlistRequest(post(big), deps)).status).toBe(413);
  });

  it('bot tuzağı dolu ise başarılı görünür ama kaydetmez', async () => {
    const { deps, sink } = makeDeps();
    const response = await handleWaitlistRequest(post({ ...valid, website: 'http://spam' }), deps);
    expect(response.status).toBe(200);
    expect(sink.entries()).toHaveLength(0);
  });

  it('hız sınırını aşınca 429 ve Retry-After verir', async () => {
    const { deps } = makeDeps({ limiter: createRateLimiter({ limit: 1, windowMs: 60_000 }) });
    expect((await handleWaitlistRequest(post(valid), deps)).status).toBe(200);
    const blocked = await handleWaitlistRequest(post(valid), deps);
    expect(blocked.status).toBe(429);
    expect(Number(blocked.headers.get('retry-after'))).toBeGreaterThanOrEqual(1);
  });

  it('kayıt hedefi yoksa 503 döner (kayıt sessizce kaybolmaz)', async () => {
    const { deps } = makeDeps({ sink: null });
    expect((await handleWaitlistRequest(post(valid), deps)).status).toBe(503);
  });

  it('kayıt hedefi hata verirse ayrıntı sızdırmadan 503 döner', async () => {
    const { deps } = makeDeps({
      sink: {
        add: () => {
          throw new Error('disk dolu: /secret/path');
        },
      },
    });
    const response = await handleWaitlistRequest(post(valid), deps);
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain('secret');
  });

  it('Turnstile etkin ve anahtar yoksa kapalı başarısız olur', async () => {
    const { deps, sink } = makeDeps({ turnstile: { enabled: true } });
    expect((await handleWaitlistRequest(post(valid), deps)).status).toBe(503);
    expect(sink.entries()).toHaveLength(0);
  });

  it('Turnstile etkinken jeton yoksa 400, geçerli jetonla 200', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ success: true })));
    const { deps } = makeDeps({
      turnstile: { enabled: true, secret: 'gizli' },
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect((await handleWaitlistRequest(post(valid), deps)).status).toBe(400);
    expect(
      (await handleWaitlistRequest(post({ ...valid, turnstileToken: 'jeton' }), deps)).status,
    ).toBe(200);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe('Turnstile doğrulayıcı', () => {
  it('kapalıyken atlanır', async () => {
    expect(await verifyTurnstile({ enabled: false }, undefined)).toBe('skipped');
  });

  it('başarısız yanıt ve ağ hatasında failed döner', async () => {
    const config = { enabled: true, secret: 's' };
    const denied = async () => new Response(JSON.stringify({ success: false }));
    expect(await verifyTurnstile(config, 't', denied as unknown as typeof fetch)).toBe('failed');
    const broken = async () => {
      throw new Error('ağ');
    };
    expect(await verifyTurnstile(config, 't', broken as unknown as typeof fetch)).toBe('failed');
    const serverError = async () => new Response('', { status: 500 });
    expect(await verifyTurnstile(config, 't', serverError as unknown as typeof fetch)).toBe(
      'failed',
    );
  });
});

describe('hız sınırlayıcı', () => {
  it('pencere dolunca sıfırlanır', () => {
    let now = 0;
    const limiter = createRateLimiter({ limit: 2, windowMs: 1000, now: () => now });
    expect(limiter.check('a')).toEqual({ allowed: true });
    expect(limiter.check('a')).toEqual({ allowed: true });
    expect(limiter.check('a')).toEqual({ allowed: false, retryAfterSeconds: 1 });
    expect(limiter.check('b')).toEqual({ allowed: true });
    now = 1000;
    expect(limiter.check('a')).toEqual({ allowed: true });
  });
});

describe('kayıt hedefi seçimi ve dosya hedefi', () => {
  let dir: string | undefined;
  afterEach(async () => {
    if (dir) await rm(dir, { recursive: true, force: true });
    dir = undefined;
  });

  it('üretimde varsayılan hedef yok, geliştirmede bellek', () => {
    expect(resolveSink({ NODE_ENV: 'production' })).toBeNull();
    expect(resolveSink({ NODE_ENV: 'development' })).toBeInstanceOf(MemoryWaitlistSink);
    expect(resolveSink({ NODE_ENV: 'production', WAITLIST_SINK: 'memory' })).toBeInstanceOf(
      MemoryWaitlistSink,
    );
    expect(resolveSink({ NODE_ENV: 'development', WAITLIST_SINK: 'none' })).toBeNull();
  });

  it('dosya hedefi satır ekler ve tekrarı yazmaz', async () => {
    dir = await mkdtemp(join(tmpdir(), 'bekleme-'));
    const file = join(dir, 'alt', 'liste.jsonl');
    const entry = {
      email: 'a@b.co',
      storeCategory: null,
      monthlyOrders: 'yok',
      marketingConsent: false,
      marketingConsentAt: null,
      privacyNoticeVersion: PRIVACY_NOTICE_VERSION,
      createdAt: '2026-11-07T10:00:00.000Z',
    };
    const sink = new FileWaitlistSink(file);
    expect(await sink.add(entry)).toBe('created');
    expect(await sink.add(entry)).toBe('duplicate');
    // Yeni örnek dosyadan okur
    expect(await new FileWaitlistSink(file).add(entry)).toBe('duplicate');
    const lines = (await readFile(file, 'utf8')).trim().split('\n');
    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0] ?? '{}')).toMatchObject({ email: 'a@b.co' });
  });
});

describe('istemci doğrulaması', () => {
  const base = {
    email: 'a@b.co',
    storeCategory: '',
    monthlyOrders: 'yok',
    marketingConsent: false,
  };

  it('geçerli değerlerde hata yok', () => {
    expect(validateWaitlistForm(base)).toEqual({});
  });

  it('boş ve geçersiz e-postayı, seçilmemiş aralığı yakalar', () => {
    expect(validateWaitlistForm({ ...base, email: '' }).email).toMatch(/yazın/);
    expect(validateWaitlistForm({ ...base, email: 'a@b' }).email).toMatch(/geçerli/);
    expect(validateWaitlistForm({ ...base, monthlyOrders: '' }).monthlyOrders).toMatch(/seçin/);
  });
});

describe('istemci paketi', () => {
  it('istemcinin kullandığı modüller zod veya sunucu şemasını içe aktarmaz (JS bütçesi)', async () => {
    const { readFile: read } = await import('node:fs/promises');
    const files = [
      'src/lib/waitlist/options.ts',
      'src/lib/waitlist/validate.ts',
      'src/components/waitlist/waitlist-form.tsx',
    ];
    for (const file of files) {
      const text = await read(file, 'utf8');
      expect(text, file).not.toMatch(/from ['"]zod['"]/);
      expect(text, file).not.toMatch(/waitlist\/schema|from '\.\/schema'/);
    }
  });
});
