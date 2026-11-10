import { describe, expect, it } from 'vitest';

import {
  defaultsSchema,
  expenseSchema,
  feeSchema,
  formFieldPath,
  mapFieldErrors,
  tariffSchema,
  toDefaultsBody,
  toExpenseBody,
  toFeeBody,
  toTariffBody,
  type ExpenseFormValues,
  type TariffFormValues,
} from '@/lib/validation/profit-settings';

const TODAY = '2026-11-10';

function tariff(over: Partial<TariffFormValues> = {}): TariffFormValues {
  return {
    agreement: 'trendyol',
    carrier: 'Trendyol Express',
    validFrom: '2026-08-10',
    vatMode: 'dahil',
    brackets: [
      { maxDesi: '2', price: '54,00' },
      { maxDesi: '5', price: '72,50' },
    ],
    ...over,
  };
}

function messages(result: ReturnType<ReturnType<typeof tariffSchema>['safeParse']>): string[] {
  return result.success ? [] : result.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`);
}

describe('tariffSchema', () => {
  const schema = tariffSchema(TODAY);

  it('geçerli girdiyi kabul eder ve gövdeyi sunucu biçiminde kurar', () => {
    const values = tariff();
    expect(schema.safeParse(values).success).toBe(true);
    expect(toTariffBody(values)).toEqual({
      agreement: 'trendyol',
      carrier: 'Trendyol Express',
      valid_from: '2026-08-10',
      price_includes_vat: true,
      brackets: [
        { max_desi: '2', price: '54.00' },
        { max_desi: '5', price: '72.50' },
      ],
    });
  });

  it('0 fiyat geçerlidir (bilerek 0)', () => {
    expect(schema.safeParse(tariff({ brackets: [{ maxDesi: '1000', price: '0' }] })).success).toBe(
      true,
    );
  });

  it('firma, başlangıç, desi ve fiyat kurallarını Türkçe iletiyle reddeder', () => {
    const result = schema.safeParse(
      tariff({
        carrier: '',
        validFrom: '1999-12-31',
        brackets: [
          { maxDesi: '0', price: '-1' },
          { maxDesi: '1001', price: '100000,01' },
          { maxDesi: '2,5555', price: 'abc' },
        ],
      }),
    );
    expect(messages(result)).toEqual([
      'carrier: Kargo firmasını seçin.',
      'validFrom: Başlangıç tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
      "brackets.0.maxDesi: Desi 0'dan büyük, en çok 1.000 olmalı.",
      'brackets.0.price: Fiyat geçerli bir sayı olmalı. Örnek: 54,50',
      "brackets.1.maxDesi: Desi 0'dan büyük, en çok 1.000 olmalı.",
      'brackets.1.price: Fiyat 0 ile 100.000 arasında olmalı.',
      'brackets.2.maxDesi: Desi en çok 2 ondalıklı olabilir.',
      'brackets.2.price: Fiyat geçerli bir sayı olmalı. Örnek: 54,50',
    ]);
  });

  it('başlangıç bugün + 366 gün sınırında geçerli, bir gün sonrası geçersiz', () => {
    expect(schema.safeParse(tariff({ validFrom: '2027-11-11' })).success).toBe(true);
    expect(schema.safeParse(tariff({ validFrom: '2027-11-12' })).success).toBe(false);
    expect(schema.safeParse(tariff({ validFrom: '' })).success).toBe(false);
  });

  it('üst desi kesin artan olmalı; ihlal eden satırın alanına yazılır', () => {
    const result = schema.safeParse(
      tariff({
        brackets: [
          { maxDesi: '5', price: '1' },
          { maxDesi: '5', price: '2' },
          { maxDesi: '3', price: '3' },
        ],
      }),
    );
    expect(messages(result)).toEqual([
      'brackets.1.maxDesi: Üst desi bir önceki kademeden büyük olmalı.',
      'brackets.2.maxDesi: Üst desi bir önceki kademeden büyük olmalı.',
    ]);
  });

  it('kademe sayısı 1-50', () => {
    expect(messages(schema.safeParse(tariff({ brackets: [] })))).toEqual([
      'brackets: En az bir desi kademesi ekleyin.',
    ]);
    const many = Array.from({ length: 51 }, (_, i) => ({ maxDesi: String(i + 1), price: '1' }));
    expect(messages(schema.safeParse(tariff({ brackets: many })))).toEqual([
      'brackets: En çok 50 kademe girilebilir.',
    ]);
    expect(schema.safeParse(tariff({ brackets: many.slice(0, 50) })).success).toBe(true);
  });
});

describe('feeSchema', () => {
  const schema = feeSchema(TODAY);

  it('0 ile 10.000 arası tutarı kabul eder', () => {
    for (const amount of ['0', '12', '10000', '10000,00']) {
      expect(schema.safeParse({ validFrom: '2026-10-01', vatMode: 'haric', amount }).success).toBe(
        true,
      );
    }
    expect(toFeeBody({ validFrom: '2026-10-01', vatMode: 'dahil', amount: '12' })).toEqual({
      valid_from: '2026-10-01',
      amount: '12.00',
      amount_includes_vat: true,
    });
  });

  it('aralık dışı ve hatalı tutarı reddeder', () => {
    for (const amount of ['', '10000,01', '1,2345', 'x']) {
      expect(schema.safeParse({ validFrom: '2026-10-01', vatMode: 'haric', amount }).success).toBe(
        false,
      );
    }
  });
});

describe('defaultsSchema', () => {
  it('boş alan kaldırma (null), değer 0 < desi <= 1000', () => {
    expect(defaultsSchema.safeParse({ desi: '' }).success).toBe(true);
    expect(toDefaultsBody({ desi: '  ' })).toEqual({ default_desi: null });
    expect(toDefaultsBody({ desi: '2,5' })).toEqual({ default_desi: '2.5' });
    expect(defaultsSchema.safeParse({ desi: '0' }).success).toBe(false);
    expect(defaultsSchema.safeParse({ desi: '1000' }).success).toBe(true);
    expect(defaultsSchema.safeParse({ desi: '1000,01' }).success).toBe(false);
    expect(defaultsSchema.safeParse({ desi: 'iki' }).success).toBe(false);
  });
});

describe('expenseSchema', () => {
  const schema = expenseSchema(TODAY);
  const base: ExpenseFormValues = {
    name: ' Paketleme ',
    kind: 'siparis_basi',
    amount: '6,5',
    percent: '',
    vatRate: '20',
    validFrom: '2026-10-01',
    validTo: '',
  };

  it('tutar tiplerinde yalnız tutar, yüzde tipinde yalnız oran doğrulanır ve gönderilir', () => {
    expect(schema.safeParse(base).success).toBe(true);
    expect(toExpenseBody(base)).toEqual({
      name: 'Paketleme',
      kind: 'siparis_basi',
      amount_excl_vat: '6.50',
      percent: null,
      vat_rate: 20,
      valid_from: '2026-10-01',
      valid_to: null,
    });
    const percent = { ...base, kind: 'satis_yuzdesi' as const, amount: '', percent: '2,5' };
    expect(schema.safeParse(percent).success).toBe(true);
    expect(toExpenseBody(percent)).toMatchObject({ amount_excl_vat: null, percent: '2.5' });
  });

  it('oran 0 < x <= 100 ve en çok 4 ondalık', () => {
    const percent = { ...base, kind: 'satis_yuzdesi' as const, amount: '' };
    expect(schema.safeParse({ ...percent, percent: '100' }).success).toBe(true);
    expect(schema.safeParse({ ...percent, percent: '0' }).success).toBe(false);
    expect(schema.safeParse({ ...percent, percent: '100,5' }).success).toBe(false);
    expect(schema.safeParse({ ...percent, percent: '1,23456' }).success).toBe(false);
    expect(schema.safeParse({ ...percent, percent: '' }).success).toBe(false);
  });

  it('ad, KDV oranı ve tarih kuralları', () => {
    expect(schema.safeParse({ ...base, name: '   ' }).success).toBe(false);
    expect(schema.safeParse({ ...base, name: 'a'.repeat(81) }).success).toBe(false);
    expect(schema.safeParse({ ...base, name: 'Ad\u0000' }).success).toBe(false);
    expect(schema.safeParse({ ...base, vatRate: '8' }).success).toBe(false);
    expect(schema.safeParse({ ...base, validTo: '2026-09-30' }).success).toBe(false);
    expect(schema.safeParse({ ...base, validTo: '2026-10-01' }).success).toBe(true);
    expect(schema.safeParse({ ...base, amount: '100000,01' }).success).toBe(false);
  });
});

describe('sunucu 422 alan eşlemesi', () => {
  it('alan yolu form yoluna çevrilir', () => {
    expect(formFieldPath('brackets.0.max_desi')).toBe('brackets.0.maxDesi');
    expect(formFieldPath('valid_from')).toBe('validFrom');
    expect(formFieldPath('amount_excl_vat')).toBe('amount');
    expect(formFieldPath('default_desi')).toBe('desi');
    expect(formFieldPath('')).toBe('');
  });

  it('kod Türkçe cümleye, bilinmeyen kod genel cümleye döner; girdi değeri yansımaz', () => {
    expect(
      mapFieldErrors([
        { field: 'brackets.1.price', code: 'price_out_of_range' },
        { field: 'valid_from', code: 'too_many_tariff_versions' },
        { field: 'carrier', code: 'garip_kod' },
      ]),
    ).toEqual([
      {
        path: 'brackets.1.price',
        message: 'Fiyat 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalı.',
      },
      { path: 'validFrom', message: 'Bu hesapta en çok 200 tarife sürümü tutulabilir.' },
      { path: 'carrier', message: 'Bu değeri kontrol edin.' },
    ]);
  });
});

// AF-01: para ve oran alanları aynı kuralı izler; 1000 kat değişebilecek biçimler gönderilemez
describe('belirsiz sayı biçimleri (AF-01)', () => {
  const feeSchemaToday = feeSchema(TODAY);
  const fee = (amount: string) => ({ validFrom: '2026-08-10', vatMode: 'dahil' as const, amount });

  it('virgülden sonra 3 hane para alanında kuruş hatasıdır, binlik sayılmaz', () => {
    const result = feeSchemaToday.safeParse(fee('12,550'));
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe(
      'Kuruş en fazla 2 hane olabilir. Binlik ayracı için nokta kullanın: 1.250,00',
    );
  });

  it('gruplamasız tek nokta belirsizdir ve virgül istenir', () => {
    const result = feeSchemaToday.safeParse(fee('12.5'));
    expect(result.error?.issues[0]?.message).toBe(
      'Ondalık için virgül kullanın (örnek: 12,50). Nokta yalnız binlik ayracıdır: 1.250',
    );
  });

  it('oran alanı da aynı kuralı izler', () => {
    const schema = expenseSchema(TODAY);
    const base: ExpenseFormValues = {
      name: 'Komisyon',
      kind: 'satis_yuzdesi',
      amount: '',
      percent: '2.5',
      vatRate: '20',
      validFrom: '2026-08-10',
      validTo: '',
    };
    const result = schema.safeParse(base);
    expect(result.error?.issues[0]?.message).toContain('Ondalık için virgül kullanın');
    expect(schema.safeParse({ ...base, percent: '2,5' }).success).toBe(true);
    // 4 haneye kadar virgül ondalıktır (1,255 oran olarak geçerli, 1255 olmaz)
    expect(toExpenseBody({ ...base, percent: '1,255' }).percent).toBe('1.255');
  });

  it('doğru gruplanmış binlik kabul edilir ve gövdeye sade ondalık olarak gider', () => {
    expect(feeSchemaToday.safeParse(fee('1.250,50')).success).toBe(true);
    expect(toFeeBody(fee('1.250,50')).amount).toBe('1250.50');
    expect(toFeeBody(fee('1.250')).amount).toBe('1250.00');
  });
});
