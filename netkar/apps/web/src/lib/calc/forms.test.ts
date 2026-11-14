import { describe, expect, it } from 'vitest';

import {
  deriveCommissionInput,
  deriveDesiInput,
  deriveProfitInput,
  readMoney,
  readPercent,
  type CommissionFormValues,
  type DesiFormValues,
  type ProfitFormValues,
} from './forms';

const commissionValues: CommissionFormValues = {
  price: '600',
  vatRate: '20',
  commissionRate: '21',
  commissionVat: 'incl',
  shipping: '',
  shippingVat: 'excl',
  serviceFee: '',
};

const profitValues: ProfitFormValues = {
  price: '600',
  vatRate: '20',
  cost: '250',
  costVat: 'excl',
  costVatRate: 'same',
  commissionRate: '21',
  commissionVat: 'incl',
  shipping: '60',
  returnShipping: '60',
  shippingVat: 'excl',
  serviceFee: '',
  adMode: 'amount',
  adAmount: '',
  roas: '',
  returnRate: '5',
  unsellableRate: '',
};

const desiValues: DesiFormValues = {
  length: '30',
  width: '20',
  height: '10',
  weight: '1',
  divisor: 'domestic',
};

describe('alan okuyucular', () => {
  it('isteğe bağlı boş para alanı 0 olur, zorunlu olan hata verir', () => {
    expect(readMoney('', { optional: true })).toEqual({ ok: true, value: 0n });
    expect(readMoney('')).toEqual({ ok: false, error: 'Bu alanı doldurun.' });
  });

  it('sıfır, ondalık fazlası ve yüzde üst sınırı için Türkçe mesaj verir', () => {
    expect(readMoney('0', { positive: true })).toMatchObject({ ok: false });
    expect(readMoney('1,234')).toEqual({ ok: false, error: 'En fazla 2 ondalık hane yazın.' });
    expect(readPercent('101')).toEqual({ ok: false, error: 'En fazla %100 yazın.' });
    expect(readPercent('15,5')).toEqual({ ok: true, value: 1550n });
  });
});

describe('komisyon formu', () => {
  it('geçerli girdiyi hesap girdisine çevirir', () => {
    const result = deriveCommissionInput(commissionValues);
    expect(result.input).toMatchObject({
      priceIncl: 60000n,
      vatRatePct: 20,
      commissionBps: 2100n,
      commissionIncludesVat: true,
      shipping: 0n,
    });
  });

  it('virgüllü ve noktalı girişi aynı sayar', () => {
    const a = deriveCommissionInput({ ...commissionValues, price: '1.234,50' });
    const b = deriveCommissionInput({ ...commissionValues, price: '1234.5' });
    expect(a.input?.priceIncl).toBe(123450n);
    expect(b.input?.priceIncl).toBe(123450n);
  });

  it('hatalı alanları adlarıyla bildirir', () => {
    const result = deriveCommissionInput({ ...commissionValues, price: 'abc', vatRate: '18' });
    expect(result.input).toBeNull();
    expect(Object.keys(result.errors).sort()).toEqual(['price', 'vatRate']);
  });
});

describe('kâr formu', () => {
  it('alış KDV oranı "aynı" ise satış KDV oranını kullanır', () => {
    const result = deriveProfitInput({ ...profitValues, vatRate: '10' });
    expect(result.input?.costVatRatePct).toBe(10);
  });

  it('ROAS seçiliyken tutar alanını, tutar seçiliyken ROAS alanını doğrulamaz', () => {
    expect(
      deriveProfitInput({ ...profitValues, adMode: 'amount', roas: 'abc' }).input,
    ).not.toBeNull();
    expect(
      deriveProfitInput({ ...profitValues, adMode: 'roas', adAmount: 'abc' }).errors,
    ).toMatchObject({ roas: expect.any(String) });
    const ok = deriveProfitInput({ ...profitValues, adMode: 'roas', roas: '4,5', adAmount: 'abc' });
    expect(ok.input?.ad).toEqual({ kind: 'roas', roasHundredths: 450n });
  });

  it('maliyet satış fiyatından yüksekse uyarır ama engellemez', () => {
    const result = deriveProfitInput({ ...profitValues, cost: '900' });
    expect(result.input).not.toBeNull();
    expect(result.warnings.join(' ')).toMatch(/Alış maliyeti/);
  });

  it('maliyet boşsa bilgi uyarısı verir', () => {
    const result = deriveProfitInput({ ...profitValues, cost: '' });
    expect(result.input?.cost).toBe(0n);
    expect(result.warnings.join(' ')).toMatch(/maliyet düşülmemiş/);
  });

  it('iade oranı 100 üstünde hata verir', () => {
    expect(deriveProfitInput({ ...profitValues, returnRate: '150' }).errors.returnRate).toBe(
      'En fazla %100 yazın.',
    );
  });
});

describe('desi formu', () => {
  it('ölçüleri onda bir cm, ağırlığı grama çevirir', () => {
    const result = deriveDesiInput({ ...desiValues, length: '25,5', weight: '1,25' });
    expect(result.input).toMatchObject({
      length: 255n,
      width: 200n,
      height: 100n,
      weightGrams: 1250n,
    });
  });

  it('boş ağırlık 0 sayılır; boş ölçü hata verir', () => {
    expect(deriveDesiInput({ ...desiValues, weight: '' }).input?.weightGrams).toBe(0n);
    expect(deriveDesiInput({ ...desiValues, height: '' }).errors.height).toBe('Bu alanı doldurun.');
  });

  it('ölçüde 1 ondalıktan fazlası ve geçersiz bölen reddedilir', () => {
    expect(deriveDesiInput({ ...desiValues, length: '30,55' }).errors.length).toMatch(/1 ondalık/);
    expect(deriveDesiInput({ ...desiValues, divisor: 'x' }).errors.divisor).toBeDefined();
  });
});
