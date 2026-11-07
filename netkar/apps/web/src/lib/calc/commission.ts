// Trendyol komisyon hesabı. Kurallar: docs/12_kar_motoru.md K02, K06, K07, K18, K21.
// Komisyon matrahı KDV dahil satış tutarıdır (K06). Komisyon tutarının KDV içerip içermediği
// teyit bekler (K07, §9 madde 1): varsayılan "KDV dahil"dir, alternatif seçilebilir.

import {
  type Bps,
  type Kurus,
  divRound,
  percentOf,
  splitExclusive,
  splitInclusive,
  type VatSplit,
} from './money';
import { SERVICE_VAT_RATE, WITHHOLDING_BPS } from './constants';

export interface CommissionInput {
  /** Satıcı indirimi düşülmüş, KDV dahil satış fiyatı */
  priceIncl: Kurus;
  /** Ürün KDV oranı (yüzde) */
  vatRatePct: number;
  /** Komisyon oranı */
  commissionBps: Bps;
  /** true: komisyon tutarı KDV dahildir (K07 varsayılanı); false: KDV üstüne eklenir */
  commissionIncludesVat: boolean;
  /** Gönderi kargo bedeli (isteğe bağlı, 0 olabilir) */
  shipping: Kurus;
  shippingIncludesVat: boolean;
  /** Platform hizmet bedeli, KDV hariç (isteğe bağlı) */
  serviceFeeExcl: Kurus;
}

export interface CommissionResult {
  price: VatSplit;
  /** Komisyon KDV hariç */
  commissionExcl: Kurus;
  commissionVat: Kurus;
  commissionIncl: Kurus;
  shipping: VatSplit;
  serviceFee: VatSplit;
  /** Stopaj (nakit akışı, gider değil): net satış KDV hariç x %1 */
  withholding: Kurus;
  /** Hakediş: satış (KDV dahil) - komisyon (KDV dahil) */
  settlement: Kurus;
  /** Kargo ve hizmet faturası kesintileri (KDV dahil) */
  invoiceDeductions: Kurus;
  /** Beklenen net tahsilat: hakediş - fatura kesintileri - stopaj */
  expectedPayout: Kurus;
}

/** K07: komisyonu KDV hariç, KDV ve KDV dahil olarak üç kalemde verir. */
export function splitCommission(
  priceIncl: Kurus,
  commissionBps: Bps,
  includesVat: boolean,
): { excl: Kurus; vat: Kurus; incl: Kurus } {
  const exactNumerator = priceIncl * commissionBps; // kuruş x (yüzde x 100); payda 10.000
  if (includesVat) {
    const incl = divRound(exactNumerator, 10000n);
    const excl = divRound(exactNumerator * 100n, 10000n * (100n + BigInt(SERVICE_VAT_RATE)));
    return { excl, vat: incl - excl, incl };
  }
  const excl = divRound(exactNumerator, 10000n);
  const vat = divRound(exactNumerator * BigInt(SERVICE_VAT_RATE), 10000n * 100n);
  return { excl, vat, incl: excl + vat };
}

export function calculateCommission(input: CommissionInput): CommissionResult {
  const price = splitInclusive(input.priceIncl, input.vatRatePct);
  const commission = splitCommission(
    input.priceIncl,
    input.commissionBps,
    input.commissionIncludesVat,
  );
  const shipping = input.shippingIncludesVat
    ? splitInclusive(input.shipping, SERVICE_VAT_RATE)
    : splitExclusive(input.shipping, SERVICE_VAT_RATE);
  const serviceFee = splitExclusive(input.serviceFeeExcl, SERVICE_VAT_RATE);

  const withholding = percentOf(price.excl, WITHHOLDING_BPS);
  const settlement = input.priceIncl - commission.incl;
  const invoiceDeductions = shipping.incl + serviceFee.incl;

  return {
    price,
    commissionExcl: commission.excl,
    commissionVat: commission.vat,
    commissionIncl: commission.incl,
    shipping,
    serviceFee,
    withholding,
    settlement,
    invoiceDeductions,
    expectedPayout: settlement - invoiceDeductions - withholding,
  };
}
