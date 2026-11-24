import { describe, expect, it } from 'vitest';

import { ApiError, NetworkError } from '@/lib/api/client';
import {
  describeAlertError,
  eventAmount,
  eventEvidence,
  eventNotes,
  eventSentence,
  isEstimated,
  parseMuteDays,
  parseTab,
  subjectInfo,
} from '@/lib/alerts/present';
import { DEDUCTION_EVENT, RETURN_EVENT, makeEvent } from '@/lib/alerts/test-fixtures';

describe('parseTab', () => {
  it('bilinen sekmeyi alır, bilinmeyeni açık sekmeye düşürür', () => {
    expect(parseTab('okundu')).toBe('okundu');
    expect(parseTab('donem')).toBe('donem');
    expect(parseTab(null)).toBe('acik');
    expect(parseTab('<script>')).toBe('acik');
  });
});

describe('parseMuteDays', () => {
  it.each([
    ['1', 1],
    ['7', 7],
    ['90', 90],
    [' 30 ', 30],
  ])('%s geçerlidir', (text, days) => {
    expect(parseMuteDays(text)).toEqual({ ok: true, days });
  });

  it.each(['', '0', '91', '-3', '7,5', '1e1', 'yedi', '1000'])('%s reddedilir', (text) => {
    const result = parseMuteDays(text);
    expect(result.ok).toBe(false);
  });
});

describe('olay sunumu', () => {
  it('zararına satışta tutar toplam zarardır', () => {
    expect(eventAmount(makeEvent())).toEqual({ label: 'Toplam zarar', value: '412.30' });
    expect(eventSentence(makeEvent())).toBe('3 satırda zarar var.');
  });

  it('kesintide tutar farktır, iade oranında tutar yoktur', () => {
    expect(eventAmount(DEDUCTION_EVENT)).toEqual({ label: 'Fazla kesinti', value: '184.20' });
    expect(eventAmount(RETURN_EVENT)).toBeNull();
    expect(eventSentence(RETURN_EVENT)).toBe('İade oranı %4,1 düzeyinden %11,3 düzeyine çıktı.');
  });

  it('bozuk ya da eksik kanıt alanı sessizce 0 yazılmaz', () => {
    const broken = makeEvent({ payload: { total_loss: 'abc', loss_line_count: null } });
    expect(eventAmount(broken)).toBeNull();
    expect(eventSentence(broken)).toBe('Bu üründe satış zararına gidiyor.');
  });

  it('yük iç içedir ({certainty, evidence}); kanıt alanları evidence altından okunur', () => {
    const real = makeEvent({
      payload: { certainty: 'kesin', evidence: { total_loss: '99.50', loss_line_count: 1 } },
    });
    expect(eventEvidence(real)).toEqual({ total_loss: '99.50', loss_line_count: 1 });
    expect(eventAmount(real)).toEqual({ label: 'Toplam zarar', value: '99.50' });
    expect(eventSentence(real)).toBe('1 satırda zarar var.');
  });

  it('geriye uyum: düz yük de okunur; evidence nesne değilse düz yük sayılır', () => {
    const flat = makeEvent({ payload: { total_loss: '12.00', loss_line_count: 2 } });
    expect(eventAmount(flat)).toEqual({ label: 'Toplam zarar', value: '12.00' });
    const odd = makeEvent({ payload: { evidence: 'metin', total_loss: '7.00' } });
    expect(eventAmount(odd)).toEqual({ label: 'Toplam zarar', value: '7.00' });
    const list = makeEvent({ payload: { evidence: [1, 2] } });
    expect(eventAmount(list)).toBeNull();
  });

  it('kesinlik: yalnız tahmini rozet gerektirir', () => {
    expect(isEstimated(makeEvent({ payload: { certainty: 'tahmini', evidence: {} } }))).toBe(true);
    expect(isEstimated(makeEvent())).toBe(false);
    expect(isEstimated(makeEvent({ payload: { evidence: {} } }))).toBe(false);
  });

  it('notlar: varsayılan desi ve eksik maliyet kalemi', () => {
    const desi = makeEvent({
      rule: 'BEKLENMEYEN_KESINTI',
      payload: { certainty: 'kesin', evidence: { difference: '5.00', default_desi_used: true } },
    });
    expect(eventNotes(desi)).toEqual(['Siparişte desi bilgisi yoktu; varsayılan desi kullanıldı.']);
    const missing = makeEvent({
      payload: { certainty: 'kesin', evidence: { total_loss: '5.00', has_missing_items: true } },
    });
    expect(eventNotes(missing)).toEqual([
      'Bazı satırlarda maliyet kalemi eksik; gerçek zarar farklı olabilir.',
    ]);
    expect(eventNotes(makeEvent())).toEqual([]);
  });

  it('konu: ürün ve sipariş bağlantısı, paket ve satır kimliği gösterilmez', () => {
    expect(subjectInfo(makeEvent())).toMatchObject({
      label: 'Ürün BRK-0001',
      href: '/panel/urunler/BRK-0001',
    });
    const order = subjectInfo(DEDUCTION_EVENT);
    expect(order?.label).toBe('Sipariş 7000123');
    expect(order?.label).not.toMatch(/pkg-1|line-1/);
    expect(order?.href).toContain('q=7000123');
    expect(subjectInfo(makeEvent({ subject: 'hesap:*' }))).toEqual({
      label: 'Tüm hesap',
      href: null,
      linkLabel: null,
    });
  });
});

describe('describeAlertError', () => {
  const api = (status: number, extra: Partial<ConstructorParameters<typeof ApiError>[0]> = {}) =>
    new ApiError({ status, ...extra });

  it('409 Türkçe ileti verir ve listeyi yeniden yükletir', () => {
    const result = describeAlertError(api(409, { code: 'alert-event-changed' }));
    expect(result.text).toMatch(/başka bir yerde değişmiş/);
    expect(result.reload).toBe(true);
  });

  it('412 eşiklerin başkasınca değiştiğini söyler ve yeniden yükletir', () => {
    const result = describeAlertError(api(412, { code: 'alert-settings-changed' }));
    expect(result.text).toMatch(/başka biri tarafından değiştirildi/);
    expect(result.reload).toBe(true);
  });

  it('429 Retry-After süresini söyler', () => {
    const result = describeAlertError(api(429, { retryAfterSeconds: 600 }));
    expect(result.text).toBe('Çok fazla deneme yaptınız. Yaklaşık 10 dakika sonra tekrar deneyin.');
    expect(result.reload).toBe(false);
  });

  it('429 başlıksızsa genel cümle', () => {
    expect(describeAlertError(api(429)).text).toMatch(/Birkaç dakika sonra/);
  });

  it('doğrulanmamış e-posta ve ağ hatası mevcut metinleri kullanır', () => {
    expect(describeAlertError(api(403, { code: 'email-not-verified' })).text).toMatch(
      /doğrulamanız/,
    );
    expect(describeAlertError(new NetworkError()).text).toMatch(/Sunucuya ulaşılamadı/);
  });
});
