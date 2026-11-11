// Kâr ayarları istek sözleşmesi: services/api/app/api/v1/profit_settings_schemas.py alan adlarından STATİK beklenti
// listesi (el ile okunup yazıldı; şema değişince bu dosya ve test birlikte güncellenir). Gövdeler `extra="forbid"`
// olduğundan fazla alan 422 verir; eksik zorunlu alan da 422 verir. Üretim kodunda kullanılmaz.
//
// Kaynak (okunan sınıflar): BracketIn, CargoTariffIn, ServiceFeeIn, VariableExpenseIn, DefaultsIn (hepsi `_Strict`);
// sorgu parametreleri: profit_settings.py (DELETE: expected_revision, confirm_affects_from, confirm_past_change).
// Yanıt tarafı: `SettingsOut` (GET profit-settings) üst düzey alanları `SETTINGS_RESPONSE_FIELDS` listesindedir.

type FieldKind =
  'string' | 'list' | 'decimal' | 'decimalOrNull' | 'date' | 'dateOrNull' | 'bool' | 'int';

interface FieldSpec {
  kind: FieldKind;
  /** Kapalı değer kümesi (Literal) */
  oneOf?: readonly (string | number)[];
}

export interface BodySpec {
  required: Record<string, FieldSpec>;
  optional: Record<string, FieldSpec>;
}

/** Her gövdede ortak, isteğe bağlı koruma alanları (CargoTariffIn vb. içinde tanımlı) */
const GUARDS: Record<string, FieldSpec> = {
  expected_revision: { kind: 'int' },
  // KULLANIMDAN KALKTI ve karara etkisi yok: panel hiç göndermemelidir (aşağıdaki testte ayrıca denetlenir)
  confirm_past_change: { kind: 'bool' },
  // date | "all" | null
  confirm_affects_from: { kind: 'date' },
};

const MONEY: FieldSpec = { kind: 'decimal' };

export const BRACKET_SPEC: BodySpec = {
  required: { max_desi: MONEY, price: MONEY },
  optional: {},
};

export const BODY_SPECS = {
  'PUT /cargo-tariffs': {
    required: {
      agreement: { kind: 'string', oneOf: ['trendyol', 'seller'] },
      carrier: { kind: 'string' },
      valid_from: { kind: 'date' },
      price_includes_vat: { kind: 'bool' },
      brackets: { kind: 'list' }, // her satır ayrıca BRACKET_SPEC ile denetlenir
    },
    optional: GUARDS,
  },
  'PUT /service-fee-estimates': {
    required: {
      valid_from: { kind: 'date' },
      amount: MONEY,
      amount_includes_vat: { kind: 'bool' },
    },
    optional: GUARDS,
  },
  'POST /variable-expenses': {
    required: {
      name: { kind: 'string' },
      kind: { kind: 'string', oneOf: ['siparis_basi', 'adet_basi', 'satis_yuzdesi'] },
      vat_rate: { kind: 'int', oneOf: [0, 1, 10, 20] },
      valid_from: { kind: 'date' },
    },
    optional: {
      amount_excl_vat: { kind: 'decimalOrNull' },
      percent: { kind: 'decimalOrNull' },
      valid_to: { kind: 'dateOrNull' },
      ...GUARDS,
    },
  },
  'PUT /defaults': {
    required: { default_desi: { kind: 'decimalOrNull' } },
    optional: GUARDS,
  },
} as const satisfies Record<string, BodySpec>;

// `PUT /variable-expenses/{id}` aynı gövdeyi (VariableExpenseIn) kullanır
export type ContractKey = keyof typeof BODY_SPECS;

/**
 * GET profit-settings yanıtının üst düzey alanları (`SettingsOut`). `legacy: true`: istemci bu alan olmayan eski
 * API'ye de uyar (alan eksikse yedek değer kullanılır); diğerleri her zaman vardır.
 */
export const SETTINGS_RESPONSE_FIELDS: Record<string, { legacy: boolean }> = {
  revision: { legacy: false },
  default_desi: { legacy: false },
  cargo_tariffs: { legacy: false },
  service_fee_estimates: { legacy: false },
  variable_expenses: { legacy: false },
  completeness: { legacy: false },
  earliest_order_day: { legacy: true }, // YYYY-AA-GG | null (İstanbul günü)
  today_istanbul: { legacy: true }, // YYYY-AA-GG
  vat_rates: { legacy: true }, // { shipping, service_fee } Decimal dizgesi
};

/** `vat_rates` alt alanları (VatRatesOut) */
export const VAT_RATES_FIELDS = ['shipping', 'service_fee'] as const;

/** Yanıtın sözleşmeyle uyumsuzlukları: şemada olmayan alan, eksik zorunlu alan, bozuk yeni alan değerleri */
export function settingsResponseViolations(body: Record<string, unknown>): string[] {
  const problems: string[] = [];
  for (const key of Object.keys(body)) {
    if (!(key in SETTINGS_RESPONSE_FIELDS)) problems.push(`${key}: yanıt şemasında yok`);
  }
  for (const [key, spec] of Object.entries(SETTINGS_RESPONSE_FIELDS)) {
    if (!spec.legacy && !(key in body)) problems.push(`${key}: zorunlu alan eksik`);
  }
  const day = body.earliest_order_day;
  if (day !== undefined && day !== null && !(typeof day === 'string' && ISO_DATE.test(day))) {
    problems.push('earliest_order_day: YYYY-AA-GG ya da null olmalı');
  }
  const today = body.today_istanbul;
  if (today !== undefined && !(typeof today === 'string' && ISO_DATE.test(today))) {
    problems.push('today_istanbul: YYYY-AA-GG olmalı');
  }
  const rates = body.vat_rates;
  if (rates !== undefined) {
    const record = (rates ?? {}) as Record<string, unknown>;
    for (const key of VAT_RATES_FIELDS) {
      const value = record[key];
      if (typeof value !== 'string' || !PLAIN_DECIMAL.test(value)) {
        problems.push(`vat_rates.${key}: sade ondalık dizge olmalı (float değil)`);
      }
    }
    for (const key of Object.keys(record)) {
      if (!(VAT_RATES_FIELDS as readonly string[]).includes(key)) {
        problems.push(`vat_rates.${key}: şemada yok`);
      }
    }
  }
  return problems;
}

/** DELETE sorgu parametreleri (gövde yok) */
export const DELETE_QUERY_PARAMS = ['expected_revision', 'confirm_affects_from'] as const;

/** Sunucudaki `_PLAIN_DECIMAL` ile aynı: işaretli, en çok 15 tam ve 10 ondalık hane (düzenli ifade yerine parça parça) */
const PLAIN_DECIMAL = {
  test(value: string): boolean {
    const [whole = '', fraction, ...rest] = value.split('.');
    if (rest.length > 0) return false;
    if (!/^-?[0-9]{1,15}$/.test(whole)) return false;
    return fraction === undefined || /^[0-9]{1,10}$/.test(fraction);
  },
};
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function checkField(name: string, value: unknown, spec: FieldSpec): string | null {
  const bad = (why: string) => `${name}: ${why}`;
  if (spec.oneOf && !spec.oneOf.includes(value as string | number))
    return bad('izinli değer değil');
  switch (spec.kind) {
    case 'string':
      return typeof value === 'string' ? null : bad('dizge olmalı');
    case 'list':
      return Array.isArray(value) ? null : bad('liste olmalı');
    case 'decimal':
      return typeof value === 'string' && PLAIN_DECIMAL.test(value)
        ? null
        : bad('sade ondalık dizge olmalı');
    case 'decimalOrNull':
      return value === null || (typeof value === 'string' && PLAIN_DECIMAL.test(value))
        ? null
        : bad('sade ondalık dizge ya da null olmalı');
    case 'date':
      if (name === 'confirm_affects_from' && value === 'all') return null;
      return typeof value === 'string' && ISO_DATE.test(value) ? null : bad('YYYY-AA-GG olmalı');
    case 'dateOrNull':
      return value === null || (typeof value === 'string' && ISO_DATE.test(value))
        ? null
        : bad('YYYY-AA-GG ya da null olmalı');
    case 'bool':
      return typeof value === 'boolean' ? null : bad('mantıksal olmalı');
    case 'int':
      return typeof value === 'number' && Number.isInteger(value) ? null : bad('tamsayı olmalı');
  }
}

/** Gövdenin şemayla uyumsuzluklarını döndürür; boş dizi: uyumlu */
export function bodyViolations(spec: BodySpec, body: Record<string, unknown>): string[] {
  const problems: string[] = [];
  for (const key of Object.keys(body)) {
    if (!(key in spec.required) && !(key in spec.optional)) {
      problems.push(`${key}: şemada yok (extra="forbid" 422 verir)`);
    }
  }
  for (const [key, fieldSpec] of Object.entries(spec.required)) {
    if (!(key in body)) problems.push(`${key}: zorunlu alan eksik`);
    else {
      const problem = checkField(key, body[key], fieldSpec);
      if (problem) problems.push(problem);
    }
  }
  for (const [key, fieldSpec] of Object.entries(spec.optional)) {
    if (key in body && body[key] !== undefined) {
      const problem = checkField(key, body[key], fieldSpec);
      if (problem) problems.push(problem);
    }
  }
  return problems;
}

/** Kademe listesi: her satır yalnız `max_desi` ve `price` taşır */
export function bracketViolations(brackets: unknown): string[] {
  if (!Array.isArray(brackets) || brackets.length === 0)
    return ['brackets: boş olmayan liste olmalı'];
  return brackets.flatMap((row, index) =>
    bodyViolations(BRACKET_SPEC, row as Record<string, unknown>).map(
      (p) => `brackets[${index}].${p}`,
    ),
  );
}

/** İstek kaydını (yöntem + yol sonu) sözleşme anahtarına çevirir; DELETE ise null */
export function contractKeyOf(method: string, pathAfterBase: string): ContractKey | null {
  if (method === 'PUT' && pathAfterBase === '/cargo-tariffs') return 'PUT /cargo-tariffs';
  if (method === 'PUT' && pathAfterBase === '/service-fee-estimates') {
    return 'PUT /service-fee-estimates';
  }
  if (
    (method === 'POST' && pathAfterBase === '/variable-expenses') ||
    (method === 'PUT' && /^\/variable-expenses\/[0-9a-f-]{36}$/.test(pathAfterBase))
  ) {
    return 'POST /variable-expenses';
  }
  if (method === 'PUT' && pathAfterBase === '/defaults') return 'PUT /defaults';
  return null;
}
