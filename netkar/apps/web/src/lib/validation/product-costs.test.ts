import { describe, expect, it } from 'vitest';

import {
  costSchema,
  describeCostCode,
  mapCostErrors,
  toCostBody,
} from '@/lib/validation/product-costs';

const TODAY = '2026-11-14';
const schema = costSchema(TODAY);

function check(over: Partial<{ unitCost: string; vatRate: string; validFrom: string }> = {}) {
  return schema.safeParse({ unitCost: '54,50', vatRate: '20', validFrom: TODAY, ...over });
}

function messages(over: Parameters<typeof check>[0]): Record<string, string> {
  const result = check(over);
  if (result.success) return {};
  return Object.fromEntries(result.error.issues.map((i) => [String(i.path[0]), i.message]));
}

describe('maliyet formu doğrulaması (tr-TR ondalık kuralı)', () => {
  it('virgüllü ve binlik noktalı tutarı kabul eder', () => {
    expect(check().success).toBe(true);
    expect(check({ unitCost: '1.250,50' }).success).toBe(true);
    expect(check({ unitCost: '54' }).success).toBe(true);
    expect(check({ unitCost: '10.000.000' }).success).toBe(true);
  });

  it('belirsiz tek noktayı reddeder ve virgül ister', () => {
    expect(messages({ unitCost: '12.5' }).unitCost).toMatch(/virgül/);
    expect(messages({ unitCost: '54.50' }).unitCost).toMatch(/virgül/);
  });

  it('İngilizce biçimi, negatifi ve harfi reddeder', () => {
    expect(check({ unitCost: '1,250.50' }).success).toBe(false);
    expect(check({ unitCost: '-5' }).success).toBe(false);
    expect(check({ unitCost: 'abc' }).success).toBe(false);
  });

  it('boş tutarı, sıfırı ve üst sınırı ayrı cümlelerle reddeder', () => {
    expect(messages({ unitCost: '' }).unitCost).toBe('Birim maliyeti yazın.');
    expect(messages({ unitCost: '0' }).unitCost).toBe("Maliyet 0'dan büyük olmalı.");
    expect(messages({ unitCost: '0,00' }).unitCost).toBe("Maliyet 0'dan büyük olmalı.");
    expect(messages({ unitCost: '10.000.001' }).unitCost).toBe(
      'Maliyet en çok 10.000.000 TL olabilir.',
    );
  });

  it('2 haneden fazla kuruşu reddeder (12,550 binlik sayılmaz)', () => {
    expect(messages({ unitCost: '12,550' }).unitCost).toMatch(/en fazla 2 hane/);
  });

  it('KDV oranı yalnız 0, 1, 10, 20', () => {
    for (const rate of ['0', '1', '10', '20']) expect(check({ vatRate: rate }).success).toBe(true);
    expect(messages({ vatRate: '18' }).vatRate).toBe('KDV oranını seçin.');
    expect(messages({ vatRate: '0,20' }).vatRate).toBe('KDV oranını seçin.');
  });

  it('geçerlilik tarihi aralığı: 2000-01-01 ile bugün + 366 gün', () => {
    expect(check({ validFrom: '2000-01-01' }).success).toBe(true);
    expect(check({ validFrom: '2027-11-15' }).success).toBe(true);
    expect(messages({ validFrom: '1999-12-31' }).validFrom).toMatch(/366 gün/);
    expect(messages({ validFrom: '2027-11-16' }).validFrom).toMatch(/366 gün/);
    expect(messages({ validFrom: '' }).validFrom).toBe('Geçerlilik tarihini seçin.');
    expect(messages({ validFrom: '2026-02-30' }).validFrom).toBe('Geçerlilik tarihini seçin.');
  });
});

describe('API gövdesi', () => {
  it('tutar kuruş biçiminde dizge, oran tamsayı dizgesi, tarih aynen gider', () => {
    expect(toCostBody({ unitCost: '1.250,5', vatRate: '10', validFrom: '2026-10-01' })).toEqual({
      valid_from: '2026-10-01',
      unit_cost_excl_vat: '1250.50',
      vat_rate: '10',
    });
    expect(toCostBody({ unitCost: '54', vatRate: '0', validFrom: TODAY }).unit_cost_excl_vat).toBe(
      '54.00',
    );
  });

  it('doğrulanmamış tutarı göndermez', () => {
    expect(() => toCostBody({ unitCost: '12.5', vatRate: '20', validFrom: TODAY })).toThrow(
      TypeError,
    );
  });

  it('gövdede yalnız API alanları vardır (fazladan alan 422 verir)', () => {
    const body = toCostBody({ unitCost: '54,50', vatRate: '20', validFrom: TODAY });
    expect(Object.keys(body).sort()).toEqual(['unit_cost_excl_vat', 'valid_from', 'vat_rate']);
  });
});

describe('sunucu hata kodu eşlemesi', () => {
  it('product_costs.py kodlarının hepsinin Türkçe karşılığı var', () => {
    const codes = [
      'cost_invalid',
      'cost_not_positive',
      'cost_too_large',
      'cost_too_many_decimals',
      'decimal_invalid',
      'vat_rate_invalid',
      'valid_from_out_of_range',
      'date_type',
    ];
    for (const code of codes) {
      expect(describeCostCode(code)).not.toBe('Bu değeri kontrol edin.');
    }
  });

  it('tanınmayan kod genel cümleye düşer, sunucu metni taşınmaz', () => {
    expect(describeCostCode('bilinmeyen_kod')).toBe('Bu değeri kontrol edin.');
  });

  it('alan adlarını form alanlarına çevirir, tanınmayanı gövde hatası yapar', () => {
    expect(
      mapCostErrors([
        { field: 'unit_cost_excl_vat', code: 'cost_not_positive' },
        { field: 'vat_rate', code: 'vat_rate_invalid' },
        { field: 'valid_from', code: 'valid_from_out_of_range' },
        { field: 'baska', code: 'extra_forbidden' },
      ]),
    ).toEqual([
      { field: 'unitCost', message: "Maliyet 0'dan büyük olmalı." },
      { field: 'vatRate', message: 'KDV oranı yüzde 0, 1, 10 ya da 20 olmalı.' },
      {
        field: 'validFrom',
        message:
          'Geçerlilik tarihi 1 Ocak 2000 ile bugünden en çok 366 gün sonrası arasında olmalı.',
      },
      { field: null, message: 'Bu değeri kontrol edin.' },
    ]);
  });
});
