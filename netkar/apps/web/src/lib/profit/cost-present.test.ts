import { describe, expect, it } from 'vitest';

import { ApiError, NetworkError } from '@/lib/api/client';
import {
  formatWait,
  checkImportFile,
  columnLabel,
  costEcho,
  costSince,
  costSummary,
  describeCostSaveError,
  describeImportError,
  parseImportReport,
  reportHeadline,
} from '@/lib/profit/cost-present';
import { costsHref, parseCostQuery, visibleProducts } from '@/lib/profit/cost-query';
import { makeCost, makeImportReport } from '@/lib/profit/cost-fixtures';

const apiError = (
  status: number,
  code?: string,
  extra: Partial<ConstructorParameters<typeof ApiError>[0]> = {},
) => new ApiError({ status, code, ...extra });

describe('maliyet gösterimi', () => {
  it('tutar, KDV ve tarih tr-TR yazılır', () => {
    const cost = makeCost({
      unit_cost_excl_vat: '1250.50',
      vat_rate: 10,
      valid_from: '2026-10-01',
    });
    expect(costSummary(cost)).toBe('1.250,50 TL KDV hariç, %10 KDV');
    expect(costSince(cost)).toBe('1 Ekim 2026 tarihinden beri geçerli');
  });

  it('"Kaydedilecek:" yansıması ayrıştırılan değeri ve KDV oranını söyler', () => {
    expect(costEcho('54,5', '20')).toEqual({
      tone: 'ok',
      text: 'Kaydedilecek: 54,50 TL KDV hariç, %20 KDV',
    });
    expect(costEcho('1.250', '1')?.text).toBe('Kaydedilecek: 1.250,00 TL KDV hariç, %1 KDV');
  });

  it('belirsiz ve fazla haneli yazımı uyarı olarak yansıtır, boşta null döner', () => {
    expect(costEcho('12.5', '20')?.tone).toBe('warn');
    expect(costEcho('12,550', '20')?.tone).toBe('warn');
    expect(costEcho('', '20')).toBeNull();
    expect(costEcho('abc', '20')).toBeNull();
  });
});

describe('tek kayıt hata cümleleri', () => {
  it('ağ, yetki, CSRF, hız sınırı ve sunucu hataları ayrı cümlelerdir', () => {
    expect(describeCostSaveError(new NetworkError())).toMatch(/kaydedilmedi/);
    expect(describeCostSaveError(apiError(403, 'forbidden'))).toMatch(/sahip ya da yönetici/);
    expect(describeCostSaveError(apiError(403, 'csrf-failed'))).toMatch(/Sayfayı yenileyip/);
    expect(describeCostSaveError(apiError(429))).toMatch(/Çok fazla kayıt/);
    expect(describeCostSaveError(apiError(404))).toMatch(/bulunamadı/);
    expect(describeCostSaveError(apiError(500))).toMatch(/kaydedilmedi/);
    expect(describeCostSaveError(new Error('x'))).toBe('Maliyet kaydedilemedi. Tekrar deneyin.');
  });
});

describe('dosya denetimi (yüklemeden önce)', () => {
  it('yalnız .csv ve .xlsx kabul edilir, büyük harfli uzantı da', () => {
    expect(checkImportFile({ name: 'maliyet.csv', size: 100 })).toEqual({ ok: true });
    expect(checkImportFile({ name: 'MALIYET.XLSX', size: 100 })).toEqual({ ok: true });
    expect(checkImportFile({ name: 'maliyet.xls', size: 100 })).toEqual({
      ok: false,
      message: 'Yalnız .csv veya .xlsx dosyası yüklenebilir.',
    });
    expect(checkImportFile({ name: 'maliyet', size: 100 }).ok).toBe(false);
  });

  it('boş dosya ve 2 MB üstü reddedilir', () => {
    expect(checkImportFile({ name: 'a.csv', size: 0 })).toEqual({
      ok: false,
      message: 'Seçtiğiniz dosya boş.',
    });
    expect(checkImportFile({ name: 'a.csv', size: 2 * 1024 * 1024 }).ok).toBe(true);
    const big = checkImportFile({ name: 'a.csv', size: 2 * 1024 * 1024 + 1 });
    expect(big.ok).toBe(false);
    expect(!big.ok && big.message).toMatch(/en fazla 2 MB/);
  });
});

describe('içe aktarma hata cümleleri', () => {
  it('sunucu slug ve durumlarına göre Türkçe cümle üretir', () => {
    expect(describeImportError(apiError(413, 'payload-too-large'))).toMatch(/en fazla 2 MB/);
    expect(describeImportError(apiError(415, 'import-unsupported-type'))).toMatch(
      /\.csv veya \.xlsx/,
    );
    expect(describeImportError(apiError(422, 'import-too-many-rows'))).toMatch(/10\.000/);
    expect(describeImportError(apiError(403, 'csrf-failed'))).toMatch(/Sayfayı yenileyip/);
    expect(describeImportError(apiError(403, 'forbidden'))).toMatch(/sahip ya da yönetici/);
    expect(describeImportError(new NetworkError())).toMatch(/Hiçbir şey kaydedilmedi/);
  });

  it('dosya geçersiz: sunucunun sabit ayrıntısı eklenir, yoksa genel cümle', () => {
    expect(
      describeImportError(
        apiError(422, 'import-file-invalid', {
          detail: 'Zorunlu sütun(lar) bulunamadı: kdv_orani.',
        }),
      ),
    ).toBe('Dosya okunamadı. Zorunlu sütun(lar) bulunamadı: kdv_orani.');
    expect(describeImportError(apiError(422, 'import-file-invalid'))).toBe('Dosya okunamadı.');
  });

  it('429 ve 503: Retry-After saniyesi varsa söylenir', () => {
    expect(describeImportError(apiError(429, undefined, { retryAfterSeconds: 5 }))).toBe(
      'Şu an çok fazla içe aktarma var. 5 saniye sonra tekrar deneyin.',
    );
    expect(describeImportError(apiError(503))).toBe(
      'Şu an çok fazla içe aktarma var. Biraz sonra tekrar deneyin.',
    );
  });
});

describe('içe aktarma raporu', () => {
  it('geçerli rapor aynen döner', () => {
    const report = makeImportReport({
      invalid: 1,
      valid: 2,
      errors: [{ row: 3, column: 'kdv_orani', message: 'x', value: '18' }],
    });
    expect(parseImportReport(report)).toEqual(report);
  });

  it('eksik alan, yanlış tür ya da bozuk hata satırı null verir (uydurma sayı gösterilmez)', () => {
    expect(parseImportReport(null)).toBeNull();
    expect(parseImportReport({})).toBeNull();
    expect(parseImportReport({ ...makeImportReport(), total: '3' })).toBeNull();
    expect(parseImportReport({ ...makeImportReport(), valid: -1 })).toBeNull();
    expect(parseImportReport({ ...makeImportReport(), errors: [{ row: 'a' }] })).toBeNull();
  });

  it('özet cümlesi durumu söyler', () => {
    expect(reportHeadline(makeImportReport({ valid: 3 }))).toBe('3 satır kaydedilmeye hazır.');
    expect(reportHeadline(makeImportReport({ valid: 2, invalid: 1 }))).toBe(
      '1 satırda hata var, 2 satır geçerli.',
    );
    expect(
      reportHeadline(makeImportReport({ committed: true, dry_run: false, created: 2, updated: 1 })),
    ).toBe('2 yeni maliyet eklendi, 1 maliyet güncellendi.');
  });

  it('sütun adları okunur etikete çevrilir', () => {
    expect(columnLabel('birim_maliyet_kdv_haric')).toBe('Birim maliyet (KDV hariç)');
    expect(columnLabel('bilinmeyen')).toBe('bilinmeyen');
  });
});

describe('maliyet ekranı adresi', () => {
  it('uyarı eylemi süzgeci taşır', () => {
    expect(costsHref({ missingOnly: true })).toBe('/panel/maliyetler?filtre=eksik');
    expect(costsHref()).toBe('/panel/maliyetler');
    expect(costsHref({ q: 'BRK 1', missingOnly: true })).toBe(
      '/panel/maliyetler?filtre=eksik&q=BRK+1',
    );
  });

  it('sorgu ayrıştırılır, arama 100 karaktere kırpılır', () => {
    const q = parseCostQuery(new URLSearchParams(`filtre=eksik&q=${'a'.repeat(150)}`));
    expect(q.missingOnly).toBe(true);
    expect(q.q).toHaveLength(100);
    expect(parseCostQuery(new URLSearchParams('filtre=baska')).missingOnly).toBe(false);
  });

  it('süzgeç yalnız maliyeti eksik satırları bırakır', () => {
    const items = [
      { cost_missing: true, id: 1 },
      { cost_missing: false, id: 2 },
    ];
    expect(visibleProducts(items, true).map((i) => i.id)).toEqual([1]);
    expect(visibleProducts(items, false)).toHaveLength(2);
  });
});

describe('bekleme süresi', () => {
  it('saniye, dakika ve saat olarak yazılır', () => {
    expect(formatWait(5)).toBe('5 saniye');
    expect(formatWait(119)).toBe('119 saniye');
    expect(formatWait(120)).toBe('2 dakika');
    expect(formatWait(3412)).toBe('57 dakika');
    expect(formatWait(7199)).toBe('120 dakika');
    expect(formatWait(7200)).toBe('2 saat');
    expect(formatWait(10801)).toBe('4 saat');
  });
});
