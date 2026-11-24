// Sahte API: ürün maliyeti uç noktaları (yalnız e2e). Gerçek backend DEĞİLDİR; sözleşme ve doğrulama kuralları
// services/api/app/api/v1/product_costs.py, product_cost_schemas.py, services/product_costs.py ve
// services/cost_import.py ile birebir aynıdır (hata kodları, mesajlar, rapor alanları, 2 MiB sınırı, CSV okuma).
// Durum bellektedir ve HESAP BAŞINADIR: oturum çerezi `maliyet-<ad>` ise hesap kimliği addan türetilir, her ad
// ilk istekte tohum veriyle başlar. Paralel testler farklı ad kullanır, birbirini etkilemez.
// Kapsam dışı (gerçekte var): XLSX okuma (yalnız CSV), kiracı kilidi, günlük hız sınırı (yalnız `hiz-siniri` adlı
// dosya 429 döner), yetkisiz rol dışındaki roller.
/* eslint-disable security/detect-unsafe-regex, security/detect-non-literal-regexp -- yalnız e2e sahte API'si: girdi test verisidir */
import { createHash } from 'node:crypto';

const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_ROWS = 10_000;
const MAX_REPORTED_ERRORS = 200;
const MAX_UNIT_COST = 10_000_000;
const ALLOWED_VAT = new Set([0, 1, 10, 20]);
const BARCODE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/;
const PLAIN_DECIMAL = /^[0-9]{1,15}(?:\.[0-9]{1,10})?$/;
const CSRF_COOKIE = '__Host-nk_csrf';

/** Hesap kimliği: ad -> UUID biçimi (testteki costAccountId ile aynı algoritma) */
export function costAccountId(name) {
  const h = createHash('sha1').update(name).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-8${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

export function costSessionName(session) {
  const match = /^maliyet-([a-z0-9-]{1,60})$/.exec(session ?? '');
  return match ? match[1] : null;
}

export function costRole(name) {
  return name.startsWith('goruntuleyici') ? 'viewer' : 'owner';
}

export function todayIstanbul(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Istanbul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const pick = (type) => parts.find((p) => p.type === type)?.value ?? '';
  return `${pick('year')}-${pick('month')}-${pick('day')}`;
}

function addDays(text, days) {
  const [y, m, d] = text.split('-').map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// --------------------------------------------------------------------------- durum

const accounts = new Map();

function seed(name) {
  const products = [
    ['BRK-0001', 'Çelik Termos 500 ml', 'TRM-500'],
    ['BRK-0002', 'Cam Matara 1 L', null],
    ['BRK-0003', 'Bambu Kesme Tahtası', 'KST-01'],
    ['BRK-0004', 'Silikon Spatula Seti', 'SPT-03'],
    ['BRK-0005', '<b>Kalın</b> Bardak', null],
    ['BRK-0006', 'Paslanmaz Çatal Bıçak 24 Parça', 'CAT-24'],
  ].map(([barcode, title, stock_code]) => ({ barcode, title, stock_code }));
  // Desen dışı barkod (sunucu yol parametresi bunu reddeder): yalnız `desenli` oturumlarında
  if (name.includes('desenli'))
    products.push({ barcode: 'ÇAY 007/A', title: 'Çay Bardağı', stock_code: null });
  const costs = new Map(); // `${barcode}|${valid_from}` -> { barcode, valid_from, unit_cost_excl_vat, vat_rate }
  const put = (barcode, valid_from, unit, vat) =>
    costs.set(`${barcode}|${valid_from}`, {
      barcode,
      valid_from,
      unit_cost_excl_vat: unit,
      vat_rate: vat,
    });
  put('BRK-0001', '2026-01-01', '48.00', 20);
  put('BRK-0001', '2026-09-01', '54.50', 20);
  put('BRK-0003', '2026-03-01', '120.00', 10);
  put('BRK-0004', '2026-05-15', '35.90', 20);
  return { products, costs };
}

function stateFor(accountId, name) {
  let state = accounts.get(accountId);
  if (!state) {
    state = seed(name);
    accounts.set(accountId, state);
  }
  return state;
}

function currentCost(state, barcode, today) {
  const rows = [...state.costs.values()]
    .filter((c) => c.barcode === barcode && c.valid_from <= today)
    .sort((a, b) => (a.valid_from < b.valid_from ? 1 : -1));
  return rows[0] ?? null;
}

function costOut(c) {
  return {
    valid_from: c.valid_from,
    unit_cost_excl_vat: c.unit_cost_excl_vat,
    vat_rate: c.vat_rate,
  };
}

// --------------------------------------------------------------------------- doğrulama (services/product_costs.py)

function isRealDate(text) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  if (!match) return false;
  const [, y, m, d] = match.map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** Dönüş: { ok: true, value } ya da { ok: false, code } (pydantic hata kodu ya da RuleError kodu) */
function checkUnitCost(raw) {
  let text;
  if (typeof raw === 'boolean') return { ok: false, code: 'decimal_invalid' };
  if (typeof raw === 'number') {
    if (!Number.isFinite(raw)) return { ok: false, code: 'decimal_invalid' };
    text = String(raw);
    if (/e/i.test(text)) return { ok: false, code: 'decimal_invalid' };
  } else if (typeof raw === 'string') {
    if (!PLAIN_DECIMAL.test(raw)) return { ok: false, code: 'decimal_invalid' };
    text = raw;
  } else {
    return { ok: false, code: 'decimal_type' };
  }
  const value = Number(text);
  if (value <= 0) return { ok: false, code: 'cost_not_positive' };
  if (value > MAX_UNIT_COST) return { ok: false, code: 'cost_too_large' };
  const fraction = text.split('.')[1] ?? '';
  if (fraction.replace(/0+$/, '').length > 2) return { ok: false, code: 'cost_too_many_decimals' };
  const [whole, frac = ''] = text.split('.');
  return { ok: true, value: `${whole}.${frac.padEnd(2, '0').slice(0, 2)}` };
}

function checkVat(raw) {
  let n;
  if (typeof raw === 'number') n = raw;
  else if (typeof raw === 'string' && PLAIN_DECIMAL.test(raw)) n = Number(raw);
  else return { ok: false, code: 'decimal_invalid' };
  return ALLOWED_VAT.has(n) ? { ok: true, value: n } : { ok: false, code: 'vat_rate_invalid' };
}

function checkValidFrom(raw, today) {
  if (typeof raw !== 'string') return { ok: false, code: 'date_type' };
  if (!isRealDate(raw)) return { ok: false, code: 'date_from_datetime_parsing' };
  if (raw < '2000-01-01' || raw > addDays(today, 366)) {
    return { ok: false, code: 'valid_from_out_of_range' };
  }
  return { ok: true, value: raw };
}

// --------------------------------------------------------------------------- yanıt yardımcıları

function problem(res, status, slug, title, extra = {}, headers = {}) {
  res.writeHead(status, {
    'Content-Type': 'application/problem+json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(JSON.stringify({ type: `urn:netkar:problem:${slug}`, title, status, ...extra }));
}

function json(res, status, body, headers = {}) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(JSON.stringify(body));
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error('too-large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function cookieValue(header = '', name) {
  for (const part of header.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return undefined;
}

function csrfOk(req) {
  const cookie = cookieValue(req.headers.cookie, CSRF_COOKIE);
  const header = req.headers['x-csrf-token'];
  return Boolean(cookie && header && cookie === header);
}

// --------------------------------------------------------------------------- CSV içe aktarma (services/cost_import.py)

const TR = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' };
function normalizeHeader(raw) {
  return String(raw ?? '')
    .toLowerCase()
    .replace(/[çğıöşüâîû]/g, (c) => TR[c])
    .replace(/[^a-z0-9]/g, '');
}

const ALIASES = {
  barkod: ['barkod', 'barcode', 'urunbarkodu', 'barkodno'],
  birim_maliyet_kdv_haric: [
    'birimmaliyetkdvharic',
    'birimmaliyet',
    'maliyet',
    'unitcost',
    'unitcostexclvat',
  ],
  kdv_orani: ['kdvorani', 'kdv', 'vatrate', 'vat', 'kdvoraniyuzde'],
  gecerlilik_tarihi: ['gecerliliktarihi', 'gecerlilik', 'gecerliliktarih', 'validfrom'],
};
const INFO_COLUMNS = new Set(['baslik', 'title', 'urunbasligi', 'urunadi']);

function parseCsv(text, delimiter) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delimiter) {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
  }
  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

class RuleError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function parseDecimalText(text) {
  const bad = new RuleError(
    'number_invalid',
    "Sayı olarak okunamadı (yalnız rakam, '.' ve ',' kullanın).",
  );
  const ambiguous = new RuleError(
    'number_ambiguous',
    'Sayı belirsiz: binlik ve ondalık ayırıcı ayırt edilemiyor (örn. 1.234 veya 1,234).',
  );
  if (text.length > 40 || !/^[0-9][0-9.,]*$/.test(text)) throw bad;
  const hasDot = text.includes('.');
  const hasComma = text.includes(',');
  if (!hasDot && !hasComma) return text;
  const group = (sep) => new RegExp(`^[1-9][0-9]{0,2}(?:\\${sep}[0-9]{3})+$`);
  if (hasDot && hasComma) {
    const decimalSep = text.lastIndexOf(',') > text.lastIndexOf('.') ? ',' : '.';
    const thousands = decimalSep === ',' ? '.' : ',';
    const at = text.lastIndexOf(decimalSep);
    const left = text.slice(0, at);
    const right = text.slice(at + 1);
    if (!right || !/^[0-9]+$/.test(right) || !group(thousands).test(left)) throw bad;
    return `${left.split(thousands).join('')}.${right}`;
  }
  const sep = hasDot ? '.' : ',';
  const parts = text.split(sep);
  if (parts.length > 2) {
    if (group(sep).test(text)) return parts.join('');
    throw bad;
  }
  const [left, right] = parts;
  if (!right) throw bad;
  if (right.length === 3 && left.length <= 3 && !left.startsWith('0')) throw ambiguous;
  return `${left}.${right}`;
}

function excerpt(value) {
  if (value === null || value === undefined) return null;
  const text = String(value)
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .slice(0, 20);
  return text === '' ? null : text;
}

function parseRow(raw, today) {
  const errors = {};
  const run = (column, action) => {
    try {
      return action();
    } catch (error) {
      if (!(error instanceof RuleError)) throw error;
      errors[column] = [error.message, raw[column]];
      return null;
    }
  };
  const blank = (v) => v === undefined || v === null || String(v).trim() === '';
  const present = (v, code = 'value_missing', message = 'Bu alan boş olamaz.') => {
    if (blank(v)) throw new RuleError(code, message);
    return String(v).trim();
  };
  const barcode = run('barkod', () => {
    const text = present(raw.barkod, 'barcode_missing', 'Barkod boş olamaz.');
    if (/^[=+\-@\t\r\n]/.test(text)) {
      throw new RuleError('barcode_formula', 'Barkod formül karakteriyle (=, +, -, @) başlayamaz.');
    }
    if (!BARCODE.test(text)) {
      throw new RuleError(
        'barcode_invalid',
        "Barkod yalnız harf, rakam, '.', '_' ve '-' içerebilir, harf veya rakamla başlamalı ve en çok 200 karakter olmalıdır.",
      );
    }
    return text;
  });
  const cost = run('birim_maliyet_kdv_haric', () => {
    const value = parseDecimalText(present(raw.birim_maliyet_kdv_haric));
    const checked = checkUnitCost(value);
    if (!checked.ok) {
      const messages = {
        cost_not_positive: 'Maliyet sıfırdan büyük olmalıdır.',
        cost_too_large: 'Maliyet en çok 10.000.000 olabilir.',
        cost_too_many_decimals: 'Maliyet en çok 2 ondalık basamak içerebilir.',
      };
      throw new RuleError(
        checked.code,
        messages[checked.code] ?? 'Maliyet geçerli bir sayı olmalıdır.',
      );
    }
    return checked.value;
  });
  const vat = run('kdv_orani', () => {
    const text = present(raw.kdv_orani).replace(/^%/, '').replace(/%$/, '').trim();
    const value = Number(parseDecimalText(text));
    if (!ALLOWED_VAT.has(value)) {
      throw new RuleError(
        'vat_rate_invalid',
        'KDV oranı yüzde olarak 0, 1, 10 veya 20 olmalıdır (örneğin %20 için 20, 0,20 değil).',
      );
    }
    return value;
  });
  let validFrom;
  if (blank(raw.gecerlilik_tarihi)) validFrom = today;
  else {
    validFrom = run('gecerlilik_tarihi', () => {
      const text = String(raw.gecerlilik_tarihi).trim();
      let iso = null;
      if (/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(text)) iso = text;
      else if (/^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$/.test(text))
        iso = `${text.slice(6)}-${text.slice(3, 5)}-${text.slice(0, 2)}`;
      if (!iso || !isRealDate(iso)) {
        throw new RuleError(
          'date_invalid',
          'Tarih YYYY-AA-GG veya GG.AA.YYYY biçiminde olmalıdır.',
        );
      }
      if (iso < '2000-01-01' || iso > addDays(today, 366)) {
        throw new RuleError(
          'valid_from_out_of_range',
          'Geçerlilik tarihi 2000-01-01 ile bugünden 366 gün sonrası arasında olmalıdır.',
        );
      }
      return iso;
    });
  }
  if (Object.keys(errors).length > 0 || !barcode || !cost || vat === null || !validFrom) {
    return { row: null, errors };
  }
  return {
    row: { barcode, valid_from: validFrom, unit_cost_excl_vat: cost, vat_rate: vat },
    errors,
  };
}

/** Dönüş: { parse } ya da { fileError: { status, slug, title, detail } } */
function parseImport(filename, data, today) {
  const name = (filename ?? '').toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() : '';
  if (ext !== 'csv' && ext !== 'xlsx') {
    return {
      fileError: {
        status: 415,
        slug: 'import-unsupported-type',
        title: 'Desteklenmeyen dosya türü',
        detail: 'Yalnız .csv veya .xlsx dosyası yüklenebilir.',
      },
    };
  }
  const invalid = (detail) => ({
    fileError: { status: 422, slug: 'import-file-invalid', title: 'Dosya geçersiz', detail },
  });
  if (data.length === 0) return invalid('Dosya boş.');
  if (ext === 'xlsx') {
    // Gerçekte XLSX okuyucu kapalıysa (defusedxml yok) 503 import-unavailable döner; sahte API XLSX'i hep kapalı sayar
    return {
      fileError: {
        status: 503,
        slug: 'import-unavailable',
        title: 'İçe aktarma şu an kullanılamıyor',
        detail:
          'XLSX içe aktarma geçici olarak kapalı. CSV kullanın veya destekle iletişime geçin.',
      },
    };
  }
  if (data.subarray(0, 2).toString() === 'PK' || data.includes(0)) {
    return invalid('Dosya içeriği CSV metni değil (ikili veri).');
  }
  const text = data.toString('utf8').replace(/^﻿/, '');
  const firstLine = text.split('\n', 1)[0];
  const count = (d) => firstLine.split(d).length - 1;
  const delimiter = [';', ',', '\t'].reduce((best, d) => (count(d) > count(best) ? d : best), ';');
  const rows = parseCsv(text, delimiter);
  if (rows.length === 0 || rows[0].every((c) => c.trim() === ''))
    return invalid('Başlık satırı bulunamadı.');
  const mapping = {};
  const ignored = [];
  rows[0].forEach((cellText, index) => {
    const key = normalizeHeader(cellText);
    if (!key) return;
    const canonical = Object.keys(ALIASES).find((n) => ALIASES[n].includes(key));
    if (!canonical) {
      if (!INFO_COLUMNS.has(key) && ignored.length < 20) ignored.push(excerpt(cellText) ?? '?');
      return;
    }
    mapping[canonical] = index;
  });
  const missing = ['barkod', 'birim_maliyet_kdv_haric', 'kdv_orani'].filter((n) => !(n in mapping));
  if (missing.length > 0) return invalid(`Zorunlu sütun(lar) bulunamadı: ${missing.join(', ')}.`);

  const result = {
    rows: [],
    issues: [],
    total: 0,
    invalid: 0,
    skipped: 0,
    ignored,
    truncated: false,
    format: 'csv',
  };
  const seen = new Map();
  const addIssue = (rowNo, column, message, value) => {
    if (result.issues.length < MAX_REPORTED_ERRORS) {
      result.issues.push({ row: rowNo, column, message, value: excerpt(value) });
    } else result.truncated = true;
  };
  for (let i = 1; i < rows.length; i += 1) {
    const row = rows[i];
    const rowNo = i + 1;
    if (row.every((c) => c.trim() === '')) continue;
    result.total += 1;
    if (result.total > MAX_ROWS) {
      return {
        fileError: {
          status: 422,
          slug: 'import-too-many-rows',
          title: 'Dosyada çok fazla satır var',
          detail: 'Dosya en çok 10.000 veri satırı içerebilir.',
        },
      };
    }
    const cell = (column) => (column in mapping ? row[mapping[column]] : undefined);
    const raw = {
      barkod: cell('barkod'),
      birim_maliyet_kdv_haric: cell('birim_maliyet_kdv_haric'),
      kdv_orani: cell('kdv_orani'),
      gecerlilik_tarihi: cell('gecerlilik_tarihi'),
    };
    const blank = (v) => v === undefined || String(v).trim() === '';
    if (
      !blank(raw.barkod) &&
      [raw.birim_maliyet_kdv_haric, raw.kdv_orani, raw.gecerlilik_tarihi].every(blank)
    ) {
      result.skipped += 1;
      continue;
    }
    let parsed = parseRow(raw, today);
    for (const [column, [message, value]] of Object.entries(parsed.errors))
      addIssue(rowNo, column, message, value);
    if (parsed.row) {
      const key = `${parsed.row.barcode}|${parsed.row.valid_from}`;
      if (seen.has(key)) {
        addIssue(
          rowNo,
          'barkod',
          `Aynı barkod ve geçerlilik tarihi satır ${seen.get(key)}'de zaten var.`,
          raw.barkod,
        );
        parsed = { row: null, errors: {} };
      } else seen.set(key, rowNo);
    }
    if (!parsed.row) result.invalid += 1;
    else result.rows.push(parsed.row);
  }
  return { parse: result };
}

function report(parse, state, { dryRun, committed, created, updated }) {
  const known = new Set(state.products.map((p) => p.barcode));
  const unknown = new Set(parse.rows.map((r) => r.barcode).filter((b) => !known.has(b))).size;
  return {
    dry_run: dryRun,
    committed,
    format: parse.format,
    total: parse.total,
    valid: parse.rows.length,
    invalid: parse.invalid,
    skipped: parse.skipped,
    unknown_barcodes: unknown,
    created,
    updated,
    errors: parse.issues,
    errors_truncated: parse.truncated,
    ignored_columns: parse.ignored,
  };
}

/** multipart/form-data gövdesinden `file` parçası: { filename, data } ya da null */
function extractFile(body, contentType) {
  const match = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType ?? '');
  if (!match) return null;
  const boundary = Buffer.from(`--${match[1] ?? match[2]}`);
  let start = body.indexOf(boundary);
  while (start !== -1) {
    const next = body.indexOf(boundary, start + boundary.length);
    if (next === -1) break;
    const part = body.subarray(start + boundary.length + 2, next - 2);
    const headerEnd = part.indexOf('\r\n\r\n');
    if (headerEnd !== -1) {
      const headers = part.subarray(0, headerEnd).toString('utf8');
      if (/name="file"/.test(headers)) {
        const filename = /filename="([^"]*)"/.exec(headers)?.[1] ?? null;
        return { filename, data: part.subarray(headerEnd + 4) };
      }
    }
    start = next;
  }
  return null;
}

// --------------------------------------------------------------------------- yönlendirme

/**
 * `/v1/marketplace-accounts/{id}/...` isteği bu modüle aitse true döner ve yanıtlar. `session`: oturum çerezi.
 * Hesap kimliği oturum adından türetilenle eşleşmezse 404 (başka kiracının hesabı gibi).
 */
export function handleCostRequest(req, res, url, session) {
  const match =
    /^\/v1\/marketplace-accounts\/([0-9a-f-]{36})\/(products(?:\/.*)?|product-costs\/.*)$/.exec(
      url.pathname,
    );
  if (!match) return false;
  if (!session || session === 'gecersiz') {
    problem(res, 401, 'unauthorized', 'Kimlik doğrulama gerekli');
    return true;
  }
  const name = costSessionName(session);
  const notFound = () => problem(res, 404, 'not-found', 'Bulunamadı');
  if (!name || costAccountId(name) !== match[1]) {
    notFound();
    return true;
  }
  const state = stateFor(match[1], name);
  const today = todayIstanbul();
  const role = costRole(name);
  const sub = match[2];
  const forbidWrite = () => {
    if (role !== 'owner') {
      problem(res, 403, 'forbidden', 'Erişim reddedildi');
      return true;
    }
    return false;
  };

  if (req.method === 'GET' && sub === 'products') {
    const limit = Number(url.searchParams.get('limit') ?? 50);
    if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
      problem(res, 422, 'validation-error', 'Doğrulama hatası', {
        detail: 'İstek gövdesi geçersiz.',
        errors: [{ field: 'limit', code: 'less_than_equal' }],
      });
      return true;
    }
    const after = url.searchParams.get('after');
    const q = (url.searchParams.get('q') ?? '').toLowerCase();
    const missingOnly = url.searchParams.get('missing') === 'true';
    let items = [...state.products].sort((a, b) => (a.barcode < b.barcode ? -1 : 1));
    // Sunucu sözleşmesi: total_missing hesabın TÜM ürünleri içindir (q, after ve missing'den bağımsız)
    const totalMissing = items.filter((p) => currentCost(state, p.barcode, today) === null).length;
    if (q)
      items = items.filter(
        (p) => p.barcode.toLowerCase().includes(q) || (p.title ?? '').toLowerCase().includes(q),
      );
    if (missingOnly) items = items.filter((p) => currentCost(state, p.barcode, today) === null);
    if (after !== null) items = items.filter((p) => p.barcode > after);
    const page = items.slice(0, limit);
    json(res, 200, {
      items: page.map((p) => {
        const cost = currentCost(state, p.barcode, today);
        return { ...p, current_cost: cost ? costOut(cost) : null, cost_missing: cost === null };
      }),
      next_cursor: items.length > limit ? page[page.length - 1].barcode : null,
      total_missing: totalMissing,
    });
    return true;
  }

  const historyMatch = /^products\/([^/]+)\/costs$/.exec(sub);
  if (historyMatch) {
    const barcode = decodeURIComponent(historyMatch[1]);
    if (!BARCODE.test(barcode)) {
      problem(res, 422, 'validation-error', 'Doğrulama hatası', {
        errors: [{ field: 'barcode', code: 'string_pattern_mismatch' }],
      });
      return true;
    }
    const known = state.products.some((p) => p.barcode === barcode);
    if (req.method === 'GET') {
      const history = [...state.costs.values()]
        .filter((c) => c.barcode === barcode)
        .sort((a, b) => (a.valid_from < b.valid_from ? 1 : -1));
      if (history.length === 0 && !known) notFound();
      else json(res, 200, { barcode, product_known: known, items: history.map(costOut) });
      return true;
    }
    if (req.method === 'PUT') {
      handleUpsert(req, res, state, barcode, known, today, forbidWrite);
      return true;
    }
  }

  if (req.method === 'POST' && sub === 'product-costs/import') {
    handleImport(req, res, state, url, today, forbidWrite);
    return true;
  }
  if (req.method === 'GET' && sub === 'product-costs/template.csv') {
    if (name.includes('sablon-429')) {
      problem(res, 429, 'rate-limited', 'Çok fazla istek', {}, { 'Retry-After': '1800' });
      return true;
    }
    const quote = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [
      ['barkod', 'baslik', 'birim_maliyet_kdv_haric', 'kdv_orani', 'gecerlilik_tarihi']
        .map(quote)
        .join(';'),
    ];
    for (const p of [...state.products].sort((a, b) => (a.barcode < b.barcode ? -1 : 1))) {
      const safe = (v) => (v && /^[=+\-@\t\r\n]/.test(v) ? `'${v}` : (v ?? ''));
      lines.push([safe(p.barcode), safe(p.title), '', '', ''].map(quote).join(';'));
    }
    res.writeHead(200, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="maliyet_sablonu.csv"',
      'Cache-Control': 'no-store',
      // Gerçekte 10.000 üründen fazlasında şablon kesilir ve bu başlık gelir
      ...(name.includes('sablon-kesik') ? { 'X-Template-Truncated': 'true' } : {}),
    });
    res.end(
      Buffer.concat([
        Buffer.from([0xef, 0xbb, 0xbf]),
        Buffer.from(`${lines.join('\r\n')}\r\n`, 'utf8'),
      ]),
    );
    return true;
  }
  notFound();
  return true;
}

function handleUpsert(req, res, state, barcode, known, today, forbidWrite) {
  if (!csrfOk(req)) {
    problem(res, 403, 'csrf-failed', 'CSRF doğrulaması başarısız', {
      detail: 'Geçerli bir X-CSRF-Token başlığı ve çerezi gerekli.',
    });
    return;
  }
  if (forbidWrite()) return;
  readBody(req, 8 * 1024).then(
    (buffer) => {
      let body;
      try {
        body = JSON.parse(buffer.toString('utf8'));
      } catch {
        body = null;
      }
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        problem(res, 422, 'validation-error', 'Doğrulama hatası', {
          detail: 'İstek gövdesi geçersiz.',
          errors: [{ field: '', code: 'model_attributes_type' }],
        });
        return;
      }
      const errors = [];
      const need = (field, check) => {
        if (!(field in body)) {
          errors.push({ field, code: 'missing' });
          return null;
        }
        const r = check(body[field]);
        if (!r.ok) errors.push({ field, code: r.code });
        return r.ok ? r.value : null;
      };
      const validFrom = need('valid_from', (v) => checkValidFrom(v, today));
      const unit = need('unit_cost_excl_vat', checkUnitCost);
      const vat = need('vat_rate', checkVat);
      for (const key of Object.keys(body)) {
        if (!['valid_from', 'unit_cost_excl_vat', 'vat_rate'].includes(key))
          errors.push({ field: key, code: 'extra_forbidden' });
      }
      if (errors.length > 0) {
        problem(res, 422, 'validation-error', 'Doğrulama hatası', {
          detail: 'İstek gövdesi geçersiz.',
          errors,
        });
        return;
      }
      const key = `${barcode}|${validFrom}`;
      const created = !state.costs.has(key);
      const row = { barcode, valid_from: validFrom, unit_cost_excl_vat: unit, vat_rate: vat };
      state.costs.set(key, row);
      json(res, 200, { barcode, product_known: known, created, cost: costOut(row) });
    },
    () => problem(res, 413, 'payload-too-large', 'İstek gövdesi çok büyük'),
  );
}

function handleImport(req, res, state, url, today, forbidWrite) {
  if (!csrfOk(req)) {
    problem(res, 403, 'csrf-failed', 'CSRF doğrulaması başarısız', {
      detail: 'Geçerli bir X-CSRF-Token başlığı ve çerezi gerekli.',
    });
    return;
  }
  if (forbidWrite()) return;
  const dryRun = (url.searchParams.get('dry_run') ?? 'true') !== 'false';
  const allowPartial = url.searchParams.get('allow_partial') === 'true';
  readBody(req, MAX_FILE_BYTES + 64 * 1024).then(
    (buffer) => {
      const file = extractFile(buffer, req.headers['content-type']);
      if (!file) {
        problem(res, 422, 'validation-error', 'Doğrulama hatası', {
          detail: 'İstek gövdesi geçersiz.',
          errors: [{ field: 'file', code: 'missing' }],
        });
        return;
      }
      if (file.data.length > MAX_FILE_BYTES) {
        problem(res, 413, 'payload-too-large', 'İstek gövdesi çok büyük', {
          detail: 'Dosya en fazla 2 MB olabilir.',
        });
        return;
      }
      if ((file.filename ?? '').startsWith('hiz-siniri')) {
        // Kiracı saatlik penceresi: Retry-After saniye cinsinden uzun olabilir
        problem(res, 429, 'rate-limited', 'Çok fazla istek', {}, { 'Retry-After': '3412' });
        return;
      }
      if ((file.filename ?? '').startsWith('devam-ediyor')) {
        problem(
          res,
          429,
          'import-in-progress',
          'İçe aktarma sürüyor',
          {
            detail:
              'Bu mağaza için bir içe aktarma zaten sürüyor. Bitmesini bekleyip tekrar deneyin.',
          },
          { 'Retry-After': '5' },
        );
        return;
      }
      const parsed = parseImport(file.filename, file.data, today);
      if (parsed.fileError) {
        const { status, slug, title, detail } = parsed.fileError;
        problem(res, status, slug, title, { detail });
        return;
      }
      const parse = parsed.parse;
      if (dryRun) {
        json(
          res,
          200,
          report(parse, state, { dryRun: true, committed: false, created: null, updated: null }),
        );
        return;
      }
      if (parse.invalid > 0 && !allowPartial) {
        problem(res, 422, 'import-validation-failed', 'İçe aktarma doğrulanamadı', {
          detail:
            'Hatalı satırlar var; hiçbir şey kaydedilmedi. Düzeltin veya allow_partial=true ile yalnız geçerli satırları kaydedin.',
          report: report(parse, state, {
            dryRun: false,
            committed: false,
            created: null,
            updated: null,
          }),
        });
        return;
      }
      let created = 0;
      let updated = 0;
      for (const row of parse.rows) {
        const key = `${row.barcode}|${row.valid_from}`;
        if (state.costs.has(key)) updated += 1;
        else created += 1;
        state.costs.set(key, row);
      }
      json(res, 200, report(parse, state, { dryRun: false, committed: true, created, updated }));
    },
    () =>
      problem(res, 413, 'payload-too-large', 'İstek gövdesi çok büyük', {
        detail: 'Dosya en fazla 2 MB olabilir.',
      }),
  );
}
