// Sahte API: güvenlik ayarları (TOTP) uç noktaları (yalnız e2e). Gerçek backend DEĞİLDİR; sözleşme
// services/api/app/api/v1/auth.py (/auth/totp/setup, enable, disable, recovery-codes) ve schemas.py ile aynıdır:
// yanıt alanları (`secret`, `otpauth_uri`, `recovery_codes`), hata kodları (`reauth-failed`, `invalid-code`,
// `email-not-verified`, `rate-limited`, `rate-limit-busy`, `totp-locked`, `totp-already-enabled`,
// `totp-not-enabled`, `totp-not-set-up`) ve durum kodları gerçektekiyle aynıdır.
// Durum bellektedir ve HESAP BAŞINADIR: oturum çerezi `guvenlik-<ad>` ise o ad kendi durumunu açar.
// Ad içindeki işaretler başlangıç durumunu belirler (paralel testler farklı ad kullanır):
//   `acik`          TOTP açık başlar (10 kurtarma kodu)      `az`      açık hesapta 2 kod kalmıştır
//   `dogrulanmamis` e-posta doğrulanmamış (tüm TOTP uçları 403 email-not-verified)
//   `gunluk`        günlük yeniden doğrulama sınırı aşıldı (429 rate-limited, Retry-After 12 saat)
//   `yogun`         sayaç servisi yoğun (503 rate-limit-busy)
//   `kilit`         ikinci faktör kilidi (429 totp-locked, Retry-After 15 dakika)
// Sahte değerler: parola SAHTE_PAROLA, geçerli doğrulama kodu SAHTE_KOD (gerçek TOTP hesaplanmaz).
// Kapsam dışı (gerçekte var): gerçek TOTP/zaman adımı, tek kullanımlık kod tüketimi, diğer oturumların iptali.
import { createHash } from 'node:crypto';

export const FAKE_PASSWORD = 'Dogru-Parola-1';
export const FAKE_TOTP_CODE = '482916';
export const FAKE_SECRET = 'NKSAHTE2ETSECRET';
const CSRF_COOKIE = '__Host-nk_csrf';
const RECOVERY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const RECOVERY_COUNT = 10;

const accounts = new Map();

/** İşaretler addaki tire ile ayrılmış parçalardır (`guvenlik-acik-az-x` -> acik, az, x); kısmi eşleşme sayılmaz */
function hasFlag(name, flag) {
  return name.split('-').includes(flag);
}

export function securitySessionName(session) {
  const match = /^guvenlik-([a-z0-9-]{1,80})$/.exec(session ?? '');
  return match ? match[1] : null;
}

/** Sahte kurtarma kodları: `generation` değiştikçe farklı, kendi içinde tekil, XXXX-XXXX-XXXX biçimi */
function makeCodes(name, generation) {
  const codes = new Set();
  let n = 0;
  while (codes.size < RECOVERY_COUNT) {
    const digest = createHash('sha256').update(`${name}|${generation}|${n}`).digest();
    n += 1;
    let raw = '';
    for (let i = 0; i < 12; i += 1) raw += RECOVERY_ALPHABET[digest[i] % RECOVERY_ALPHABET.length];
    codes.add(`${raw.slice(0, 4)}-${raw.slice(4, 8)}-${raw.slice(8, 12)}`);
  }
  return [...codes].sort();
}

function stateFor(name) {
  let state = accounts.get(name);
  if (!state) {
    const enabled = hasFlag(name, 'acik');
    state = {
      enabled,
      setupDone: false,
      generation: 0,
      codes: enabled ? makeCodes(name, 0) : [],
      verified: !hasFlag(name, 'dogrulanmamis'),
    };
    if (enabled && hasFlag(name, 'az')) state.codes = state.codes.slice(0, 2);
    accounts.set(name, state);
  }
  return state;
}

/** GET /v1/me alanları (me.py: totp_enabled, email_verified, recovery_codes_remaining) */
export function securityMe(name) {
  const state = stateFor(name);
  return {
    totp_enabled: state.enabled,
    email_verified: state.verified,
    recovery_codes_remaining: state.enabled ? state.codes.length : 0,
  };
}

function problem(res, status, slug, title, extra = {}, headers = {}) {
  res.writeHead(status, {
    'Content-Type': 'application/problem+json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(JSON.stringify({ type: `urn:netkar:problem:${slug}`, title, status, ...extra }));
}

function readJson(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        resolve(null);
      }
    });
  });
}

function validation(res, fields) {
  problem(res, 422, 'validation-error', 'Doğrulama hatası', {
    detail: 'İstek gövdesi geçersiz.',
    errors: fields.map((field) => ({ field, code: 'invalid' })),
  });
}

/** Gövde yalnız beklenen alanları içermeli (backend `_Strict`: fazla alan 422) ve hepsi dizge olmalı */
function checkBody(res, body, allowed) {
  if (!body || typeof body !== 'object') return (validation(res, ['body']), false);
  const keys = Object.keys(body);
  const bad = keys.filter((k) => !allowed.includes(k));
  const missing = allowed.filter((k) => typeof body[k] !== 'string' || body[k] === '');
  if (bad.length > 0 || missing.length > 0) return (validation(res, [...bad, ...missing]), false);
  return true;
}

const ROUTES = new Set(['setup', 'enable', 'disable', 'recovery-codes']);

/**
 * `POST /v1/auth/totp/<işlem>` bu modüle aitse true döner ve yanıtlar (yanıt eşzamansız tamamlanır).
 * `session`: oturum çerezi, `cookies`: çözümlenmiş çerezler (CSRF çift gönderim denetimi için).
 */
export function handleSecurityRequest(req, res, url, session, cookies = {}) {
  const match = /^\/v1\/auth\/totp\/([a-z-]+)$/.exec(url.pathname);
  if (!match || !ROUTES.has(match[1]) || req.method !== 'POST') return false;
  const action = match[1];
  void (async () => {
    if (!session || session === 'gecersiz') {
      return problem(res, 401, 'unauthorized', 'Kimlik doğrulama gerekli');
    }
    // Çift gönderim CSRF: başlık ile çerez aynı olmalı (middleware.py)
    const header = req.headers['x-csrf-token'];
    if (!header || header !== cookies[CSRF_COOKIE]) {
      return problem(res, 403, 'csrf-failed', 'Erişim reddedildi');
    }
    const name = securitySessionName(session);
    if (!name) return problem(res, 404, 'not-found', 'Bulunamadı');
    const state = stateFor(name);
    // VerifiedAuthDep: doğrulanmamış hesap yeniden doğrulamaya bile ulaşamaz
    if (!state.verified) {
      return problem(res, 403, 'email-not-verified', 'Erişim reddedildi', {
        detail: 'E-posta adresinizi doğrulayın.',
      });
    }
    const body = await readJson(req);
    const allowed = action === 'setup' ? ['password'] : ['code', 'password'];
    if (!checkBody(res, body, allowed)) return;

    // Yeniden doğrulama sayaçları (_reauthenticate): önce 15 dakikalık, sonra günlük sınır
    if (hasFlag(name, 'yogun')) {
      return problem(
        res,
        503,
        'rate-limit-busy',
        'Hız sınırı servisi yoğun',
        { detail: 'Şu an çok sayıda istek işleniyor. Kısa süre sonra tekrar deneyin.' },
        { 'Retry-After': '2' },
      );
    }
    if (hasFlag(name, 'gunluk')) {
      return problem(
        res,
        429,
        'rate-limited',
        'Çok fazla istek',
        { detail: 'Çok fazla deneme yapıldı. Lütfen daha sonra tekrar deneyin.' },
        { 'Retry-After': '43200' },
      );
    }
    if (hasFlag(name, 'kilit') && action !== 'setup') {
      return problem(
        res,
        429,
        'totp-locked',
        'Çok fazla istek',
        { detail: 'Çok fazla hatalı deneme yapıldı.' },
        { 'Retry-After': '900' },
      );
    }
    if (body.password !== FAKE_PASSWORD) {
      return problem(res, 403, 'reauth-failed', 'Erişim reddedildi', {
        detail: 'Kimlik doğrulanamadı.',
      });
    }
    const invalidCode = () =>
      problem(res, 403, 'invalid-code', 'Erişim reddedildi', { detail: 'Kod geçersiz.' });
    const json = (status, payload) => {
      res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify(payload));
    };

    if (action === 'setup') {
      if (state.enabled) {
        return problem(res, 409, 'totp-already-enabled', 'Çakışma', {
          detail: 'TOTP zaten etkin.',
        });
      }
      state.setupDone = true;
      return json(200, {
        secret: FAKE_SECRET,
        otpauth_uri: `otpauth://totp/NetKar:ad%40ornek.com?secret=${FAKE_SECRET}&issuer=NetKar`,
      });
    }
    if (action === 'enable') {
      if (state.enabled) {
        return problem(res, 409, 'totp-already-enabled', 'Çakışma', {
          detail: 'TOTP zaten etkin.',
        });
      }
      if (!state.setupDone) {
        return problem(res, 409, 'totp-not-set-up', 'Çakışma', {
          detail: 'Önce /v1/auth/totp/setup çağrılmalı.',
        });
      }
      if (!/^\d{6}$/.test(body.code)) return validation(res, ['code']);
      if (body.code !== FAKE_TOTP_CODE) return invalidCode();
      state.enabled = true;
      state.generation += 1;
      state.codes = makeCodes(name, state.generation);
      return json(200, { recovery_codes: state.codes });
    }
    // disable ve recovery-codes: TOTP açık olmalı; kod yenilemede yalnız 6 haneli TOTP kodu kabul edilir
    const isTotp = /^\d{6}$/.test(body.code);
    if (action === 'recovery-codes' && !isTotp) {
      if (body.code.length > 20) return validation(res, ['code']);
      if (!state.enabled) {
        return problem(res, 409, 'totp-not-enabled', 'Çakışma', { detail: 'TOTP etkin değil.' });
      }
      return invalidCode();
    }
    if (state.enabled) {
      const normalized = body.code.replace(/[- ]/g, '').toUpperCase();
      const usable = isTotp
        ? body.code === FAKE_TOTP_CODE
        : state.codes.some((code) => code.replace(/-/g, '') === normalized);
      if (!usable) return invalidCode();
    }
    if (!state.enabled) {
      return problem(res, 409, 'totp-not-enabled', 'Çakışma', { detail: 'TOTP etkin değil.' });
    }
    if (action === 'disable') {
      state.enabled = false;
      state.setupDone = false;
      state.codes = [];
      res.writeHead(204, { 'Cache-Control': 'no-store' });
      return res.end();
    }
    state.generation += 1;
    state.codes = makeCodes(name, state.generation);
    return json(200, { recovery_codes: state.codes });
  })();
  return true;
}
