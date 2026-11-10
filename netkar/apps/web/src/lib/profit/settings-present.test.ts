import { describe, expect, it } from 'vitest';

import {
  carrierLabel,
  carrierValue,
  confirmCopy,
  describeExpenseAmount,
  describeValidity,
  historyEntryView,
  setupProgressText,
  setupSteps,
  vatPair,
} from '@/lib/profit/settings-present';
import {
  makeCompleteness,
  makeExpense,
  makeFee,
  makeHistoryItem,
  makeTariff,
} from '@/lib/profit/settings-fixtures';

// formatTRY 'code' stili "TL" öncesinde bölünmez boşluk (U+00A0) kullanır; karşılaştırma için normal boşluğa çevrilir.
const plain = (text: string) => text.replace(/\u00a0/g, ' ');

describe('onay penceresi metinleri (ADR-0007 §5.2 madde 1, birebir)', () => {
  it('tarihli değişiklik', () => {
    expect(confirmCopy('dated', '2026-10-01')).toEqual({
      title: 'Geçmiş raporlar değişecek',
      body: 'Bu değişiklik 1 Ekim 2026 ve sonrasındaki siparişlerin kâr hesabını değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki değer ayar geçmişinde saklanır.',
    });
  });

  it('varsayılan desi (tarihsiz)', () => {
    const expected = {
      title: 'Geçmiş raporlar değişecek',
      body: 'Siparişinde desi bilgisi olmayan tüm geçmiş siparişlerin kargo tahmini değişir.',
    };
    expect(confirmCopy('defaults', null)).toEqual(expected);
    // Tarihsiz etki her zaman bu metni verir
    expect(confirmCopy('dated', null)).toEqual(expected);
  });

  it('kargo tarifesi geri çekme', () => {
    expect(confirmCopy('retract-cargo', '2026-10-01').body).toBe(
      "Bu sürüm geri çekilirse 1 Ekim 2026 sonrası siparişlerde kargo önceki sürümden ya da 'diğer firmalar' tarifesinden hesaplanır; hiçbiri yoksa kargo 'eksik' görünür ve net kâr hesaplanamaz.",
    );
  });

  it('ADR tanımsız geri çekmelerde (hizmet bedeli, gider) tarihli genel metin', () => {
    expect(confirmCopy('retract-other', '2026-10-01').body).toContain(
      'Bu değişiklik 1 Ekim 2026 ve sonrasındaki siparişlerin kâr hesabını değiştirir.',
    );
  });
});

describe('liste özetleri', () => {
  it('KDV dahil ve hariç eşleşmesi', () => {
    expect(plain(vatPair('54.00', '45.00', true))).toBe('54,00 TL KDV dahil = 45,00 TL KDV hariç');
    expect(plain(vatPair('45.00', '45.00', false))).toBe('45,00 TL KDV hariç');
  });

  it('firma adı, yedek ve boş ad', () => {
    expect(carrierLabel('*')).toBe('Diğer firmalar');
    expect(carrierLabel('')).toBe('Diğer firmalar');
    expect(carrierLabel('Yurtiçi Kargo')).toBe('Yurtiçi Kargo');
    // AB-04: boş ad `*` önerisine eşlenir
    expect(carrierValue('')).toBe('*');
    expect(carrierValue('Yurtiçi Kargo')).toBe('Yurtiçi Kargo');
  });

  it('gider tutarı ve geçerlilik', () => {
    expect(plain(describeExpenseAmount(makeExpense()))).toBe('Sipariş başına 6,50 TL (KDV hariç)');
    expect(
      plain(describeExpenseAmount(makeExpense({ kind: 'adet_basi', amount_excl_vat: '1.00' }))),
    ).toBe('Adet başına 1,00 TL (KDV hariç)');
    expect(
      describeExpenseAmount(
        makeExpense({ kind: 'satis_yuzdesi', amount_excl_vat: null, percent: '2.5' }),
      ),
    ).toBe('Satış tutarının %2,5');
    expect(describeValidity('2026-10-01', null)).toBe('1 Ekim 2026 tarihinden itibaren');
    expect(describeValidity('2026-10-01', '2026-12-31')).toBe(
      '1 Ekim 2026 ile 31 Aralık 2026 arası',
    );
  });

  it('kurulum adımları completeness bayraklarından', () => {
    const steps = setupSteps(makeCompleteness({ service_fee_estimate_defined: false }));
    expect(steps.map((s) => [s.id, s.done])).toEqual([
      ['kargo', true],
      ['hizmet-bedeli', false],
    ]);
    expect(setupProgressText(steps)).toBe("2 adımdan 1'i tamam");
    expect(setupProgressText(setupSteps(makeCompleteness()))).toBe("2 adımdan 2'si tamam");
    expect(
      setupProgressText(
        setupSteps(
          makeCompleteness({ cargo_tariff_defined: false, service_fee_estimate_defined: false }),
        ),
      ),
    ).toBe("2 adımdan 0'ı tamam");
  });
});

describe('historyEntryView', () => {
  it('tarife değişikliği: kişi rolü, fark ve onaylı geçmiş rozeti', () => {
    const view = historyEntryView(makeHistoryItem());
    expect(view.when).toBe('10 Kasım 2026, 14:35');
    expect(view.who).toBe('Yönetici');
    expect(view.headline).toBe('Trendyol Express tarifesi (başlangıç 1 Ekim 2026) değiştirildi');
    expect(view.details).toEqual(['2 desi 54,00 → 60,00 (KDV dahil)']);
    expect(view.badges).toEqual([{ label: 'Geçmişi etkiledi (onaylı)', tone: 'warning' }]);
  });

  it('kademe eklendi, kaldırıldı ve giriş biçimi değişti', () => {
    const replaced = makeTariff();
    const next = makeTariff({
      price_includes_vat: false,
      brackets: [
        { max_desi: '2.00', price: '45.00', price_excl_vat: '45.00' },
        { max_desi: '10.00', price: '90.00', price_excl_vat: '90.00' },
      ],
    });
    const view = historyEntryView(makeHistoryItem({ record: next, replaced_record: replaced }));
    expect(view.details).toEqual([
      'Giriş biçimi KDV dahil yerine KDV hariç oldu',
      '2 desi 54,00 → 45,00 (KDV hariç)',
      '10 desi kademesi eklendi: 90,00 (KDV hariç)',
      '5 desi kademesi kaldırıldı',
    ]);
  });

  it('geri çekme rozeti, onaysız ilk girişte geçmiş rozeti yok', () => {
    const retracted = historyEntryView(
      makeHistoryItem({ action: 'geri_cek', replaced_record: null }),
    );
    expect(retracted.headline).toBe(
      'Trendyol Express tarifesi (başlangıç 1 Ekim 2026) geri çekildi',
    );
    expect(retracted.badges.map((b) => b.label)).toEqual([
      'Geri çekildi',
      'Geçmişi etkiledi (onaylı)',
    ]);

    const first = historyEntryView(
      makeHistoryItem({
        action: 'ekle',
        past_change_confirmed: false,
        replaced_record: null,
        record: makeTariff({
          agreement: 'seller',
          carrier: '*',
          brackets: [{ max_desi: '1000.00', price: '0.00', price_excl_vat: '0.00' }],
        }),
      }),
    );
    expect(first.headline).toBe(
      'Diğer firmalar tarifesi (kendi anlaşmanız, başlangıç 1 Ekim 2026) eklendi',
    );
    expect(first.details).toEqual(['1 kademe (KDV dahil)', '0 girildi']);
    expect(first.badges).toEqual([]);
  });

  it('hizmet bedeli ve gider farkları', () => {
    const fee = historyEntryView(
      makeHistoryItem({
        item: 'service_fee_estimate',
        record: makeFee({ amount: '15.00' }),
        replaced_record: makeFee(),
      }),
    );
    expect(fee.headline).toBe('Hizmet bedeli tahmini (başlangıç 1 Ekim 2026) değiştirildi');
    expect(fee.details).toEqual(['12,00 KDV dahil → 15,00 KDV dahil']);

    const expense = historyEntryView(
      makeHistoryItem({
        item: 'variable_expense',
        record: makeExpense({ amount_excl_vat: '8.00', valid_to: '2026-12-31', vat_rate: 10 }),
        replaced_record: makeExpense(),
      }),
    );
    expect(expense.headline).toBe('Paketleme gideri (başlangıç 1 Ekim 2026) değiştirildi');
    expect(expense.details.map(plain)).toEqual([
      'Sipariş başına 6,50 TL (KDV hariç) → Sipariş başına 8,00 TL (KDV hariç)',
      'KDV oranı %20 → %10',
      'Bitiş: süresiz → 31 Aralık 2026',
    ]);
  });

  it('varsayılan desi, taşıma kaydı ve kişisi olmayan kayıt', () => {
    const desi = historyEntryView(
      makeHistoryItem({
        item: 'defaults',
        action: 'ekle',
        record: null,
        replaced_record: null,
        default_desi_before: null,
        default_desi_after: '3.00',
        affects_past: true,
        past_change_confirmed: false,
      }),
    );
    expect(desi.headline).toBe('Varsayılan desi eklendi');
    expect(desi.details).toEqual(['tanımsız → 3']);

    const move = historyEntryView(
      makeHistoryItem({
        item: 'tasima',
        action: 'tasima',
        changed_by: null,
        record: null,
        replaced_record: null,
      }),
    );
    expect(move.headline).toBe('Ayarlar sürüm geçmişi düzenine taşındı');
    expect(move.who).toBe('Silinmiş kullanıcı');
    expect(
      historyEntryView(makeHistoryItem({ changed_by: { user_id: 'x', role: null } })).who,
    ).toBe('Eski kullanıcı');
  });
});
