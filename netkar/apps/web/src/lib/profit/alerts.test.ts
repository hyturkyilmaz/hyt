import { describe, expect, it } from 'vitest';

import type { AlertCount } from '@/lib/api/profit';
import {
  buildAlertGroups,
  deductionRows,
  totalAlertCount,
  unavailableAlertNames,
} from '@/lib/profit/alerts';
import { makeAlertItem } from '@/lib/profit/test-fixtures';

const count = (code: string, n: number, message = 'API metni'): AlertCount => ({
  code,
  count: n,
  message,
});

describe('buildAlertGroups', () => {
  it('para kaybettirenler üstte, kurulum ayrı grupta, kontrol en altta', () => {
    const groups = buildAlertGroups([
      count('IADE_KAYDI_BEKLENIYOR', 1),
      count('MALIYET_EKSIK', 2),
      count('BEKLENMEYEN_KESINTI', 4),
      count('ZARAR', 3),
    ]);
    expect(groups.map((g) => g.id)).toEqual(['loss', 'setup', 'check']);
    expect(groups[0]?.cards.map((c) => c.code)).toEqual(['ZARAR', 'BEKLENMEYEN_KESINTI']);
    expect(groups[0]?.title).toBe('Para kaybettirenler');
    expect(groups[1]?.title).toBe('Kurulum');
  });

  it('eylemler UX §8.3 ile uyumlu', () => {
    const cards = buildAlertGroups([
      count('ZARAR', 1),
      count('MALIYET_EKSIK', 1),
      count('KARGO_TARIFESI_EKSIK', 1),
      count('HIZMET_BEDELI_TAHMINI_EKSIK', 1),
      count('BEKLENMEYEN_KESINTI', 1),
      count('IADE_KAYDI_BEKLENIYOR', 1),
    ]).flatMap((g) => g.cards);
    const byCode = Object.fromEntries(cards.map((c) => [c.code, c]));
    const href = (code: string) => {
      const action = byCode[code]?.action;
      return action?.kind === 'link' ? action.href('7d') : null;
    };
    expect(href('ZARAR')).toBe('/panel/urunler?range=7d&filter=loss');
    expect(href('MALIYET_EKSIK')).toBe('/panel/urunler?range=7d&filter=missing_cost');
    expect(href('KARGO_TARIFESI_EKSIK')).toBe('/panel/ayarlar#kargo');
    expect(href('HIZMET_BEDELI_TAHMINI_EKSIK')).toBe('/panel/ayarlar#hizmet-bedeli');
    expect(byCode['BEKLENMEYEN_KESINTI']?.action?.kind).toBe('details');
    expect(byCode['IADE_KAYDI_BEKLENIYOR']?.action).toBeNull();
    expect(byCode['IADE_KAYDI_BEKLENIYOR']?.tone).toBe('info');
  });

  it('dönem geneli kodlar işaretlenir', () => {
    const [group] = buildAlertGroups([count('KARGO_EKSIK_SATIRLAR_VAR', 1)]);
    expect(group?.cards[0]?.periodLevel).toBe(true);
  });

  it('tanınmayan kod genel kartta gösterilir, metin kırpılır, çökmez', () => {
    const long = 'x'.repeat(500);
    const groups = buildAlertGroups([
      count('YENI_KOD_B', 2, long),
      count('YENI_KOD_A', 1, '<img src=x onerror=alert(1)>'),
      count('ZARAR', 1),
    ]);
    expect(groups.map((g) => g.id)).toEqual(['loss', 'other']);
    const other = groups[1]?.cards ?? [];
    expect(other.map((c) => c.code)).toEqual(['YENI_KOD_A', 'YENI_KOD_B']);
    expect(other[0]?.known).toBe(false);
    expect(other[0]?.action).toBeNull();
    // Metin olduğu gibi (düz metin) taşınır; basım tarafı metin düğümüdür
    expect(other[0]?.sentence).toBe('<img src=x onerror=alert(1)>');
    expect(other[1]?.sentence.length).toBeLessThan(300);
  });

  it('prototip anahtarları ve bozuk girdi tanınan kod sayılmaz', () => {
    const groups = buildAlertGroups([
      count('constructor', 1),
      count('__proto__', 1),
      count('ZARAR', 0),
      count('ZARAR', Number.NaN),
      count('', 3),
      { code: 'MALIYET_EKSIK', count: 2, message: 5 as unknown as string },
    ]);
    expect(groups.flatMap((g) => g.cards.map((c) => c.code)).sort()).toEqual([
      'MALIYET_EKSIK',
      '__proto__',
      'constructor',
    ]);
    expect(groups.find((g) => g.id === 'other')?.cards.every((c) => !c.known)).toBe(true);
  });

  it('aynı kodun sayıları toplanır, boş liste boş grup verir', () => {
    expect(buildAlertGroups([count('ZARAR', 2), count('ZARAR', 3)])[0]?.cards[0]?.count).toBe(5);
    expect(buildAlertGroups([])).toEqual([]);
    expect(totalAlertCount([count('ZARAR', 2), count('MALIYET_EKSIK', 3)])).toBe(5);
  });
});

describe('unavailableAlertNames', () => {
  it('bilinen adlar Türkçe, bilinmeyenler tek genel ad; sistem gerekçesi taşınmaz', () => {
    expect(
      unavailableAlertNames([
        { code: 'REKLAM_KARI_YIYOR', reason: 'ad_spend yok' },
        { code: 'IADE_ORANI_ARTISI', reason: 'S6' },
        { code: 'X', reason: 'a' },
        { code: 'Y', reason: 'b' },
      ]),
    ).toEqual(['Reklam kârı yiyor', 'İade oranı artışı', 'Henüz hesaplanmayan uyarı']);
  });
});

describe('deductionRows', () => {
  it('uyarı kaleminden sipariş, barkod ve fark alır; eksik alanlar null', () => {
    const rows = deductionRows([
      makeAlertItem(),
      makeAlertItem({ order_number: null, barcode: undefined, difference: null }),
    ]);
    expect(rows[0]).toMatchObject({
      orderNumber: '10004',
      barcode: 'BRK-0001',
      difference: '75.00',
      threshold: '5.00',
    });
    expect(rows[1]).toMatchObject({ orderNumber: null, barcode: null, difference: null });
    expect(new Set(rows.map((r) => r.key)).size).toBe(2);
  });
});
