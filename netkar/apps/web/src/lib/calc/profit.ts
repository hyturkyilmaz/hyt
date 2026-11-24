// Ürün başına tahmini net kâr. Kurallar: docs/12_kar_motoru.md K01, K02, K07, K10, K16, K18, K20, K25.
// Tüm giderler KDV hariç kalemlerle toplanır; KDV ve stopaj kâra girmez (K18, K20).
// Her kalem bir kez kuruşa yuvarlanır, net kâr yuvarlanmış kalemlerin farkıdır (K01).

import { SERVICE_VAT_RATE, WITHHOLDING_BPS } from './constants';
import { splitCommission } from './commission';
import {
  type Bps,
  type Kurus,
  divRound,
  percentOf,
  splitExclusive,
  splitInclusive,
  type VatSplit,
} from './money';
import * as R from './rational';

export type AdInput =
  /** Sipariş başına reklam harcaması, KDV hariç */
  | { kind: 'amount'; amount: Kurus }
  /** ROAS, iki ondalıklı tamsayı olarak (4,50 -> 450n). Harcama = KDV dahil satış / ROAS */
  | { kind: 'roas'; roasHundredths: bigint };

export interface ProfitInput {
  priceIncl: Kurus;
  vatRatePct: number;
  cost: Kurus;
  costIncludesVat: boolean;
  /** Alış KDV oranı (yüzde) */
  costVatRatePct: number;
  commissionBps: Bps;
  commissionIncludesVat: boolean;
  shipping: Kurus;
  /** Kargo ve iade kargosu için ortak: tutarlar KDV dahil mi */
  shippingIncludesVat: boolean;
  returnShipping: Kurus;
  /** Platform hizmet bedeli, KDV hariç, sipariş başı */
  serviceFeeExcl: Kurus;
  ad: AdInput;
  /** Beklenen iade oranı (sipariş sayısına göre) */
  returnRateBps: Bps;
  /** İade edilenlerin satılamaz hale gelen payı (maliyeti gider kalır) */
  unsellableBps: Bps;
}

export interface ProfitResult {
  salesIncl: Kurus;
  salesExcl: Kurus;
  salesVat: Kurus;
  cost: Kurus;
  commissionExcl: Kurus;
  commissionVat: Kurus;
  shipping: Kurus;
  serviceFee: Kurus;
  ad: Kurus;
  /** İade öncesi net kâr */
  profitBeforeReturns: Kurus;
  /** Beklenen iade payı (kârdan düşen) */
  returnCost: Kurus;
  /** İade payı sonrası net kâr */
  netProfit: Kurus;
  /** Net kâr marjı (net satış KDV hariç üzerinden), yüzde puanının yüzde biri; satış 0 ise null */
  marginBps: Bps | null;
  /** İade öncesi KDV etkisi (bilgi, K20) */
  vatEffect: Kurus;
  /** Stopaj (nakit akışı, gider değil, K18) */
  withholding: Kurus;
  /** Başabaş satış fiyatı (KDV dahil); bu girdilerle hiçbir fiyatta kâr yoksa null */
  breakEvenPrice: Kurus | null;
  /** Başabaş ROAS (ciro KDV hariç); reklam öncesi kâr 0 veya negatifse null */
  breakEvenRoasExcl: bigint | null;
  /** Başabaş ROAS (ciro KDV dahil, panel ROAS'ıyla karşılaştırmak için); aynı koşulda null */
  breakEvenRoasIncl: bigint | null;
}

function splitCost(input: ProfitInput): VatSplit {
  return input.costIncludesVat
    ? splitInclusive(input.cost, input.costVatRatePct)
    : splitExclusive(input.cost, input.costVatRatePct);
}

function splitService(amount: Kurus, includesVat: boolean): VatSplit {
  return includesVat
    ? splitInclusive(amount, SERVICE_VAT_RATE)
    : splitExclusive(amount, SERVICE_VAT_RATE);
}

function adExcl(input: ProfitInput): Kurus {
  if (input.ad.kind === 'amount') return input.ad.amount;
  // ROAS = ciro / harcama; harcama = KDV dahil satış / ROAS (varsayım: harcama KDV hariç sayılır)
  return divRound(input.priceIncl * 100n, input.ad.roasHundredths);
}

/** Kârı hesaplar. Başabaş ve ROAS alanları için `withBreakEven=false` ile özyinelemeyi keser. */
function core(input: ProfitInput) {
  const sales = splitInclusive(input.priceIncl, input.vatRatePct);
  const cost = splitCost(input);
  const commission = splitCommission(
    input.priceIncl,
    input.commissionBps,
    input.commissionIncludesVat,
  );
  const shipping = splitService(input.shipping, input.shippingIncludesVat);
  const returnShipping = splitService(input.returnShipping, input.shippingIncludesVat);
  const service = splitExclusive(input.serviceFeeExcl, SERVICE_VAT_RATE);
  const adAmount = adExcl(input);
  const adSplit = splitExclusive(adAmount, SERVICE_VAT_RATE);

  const profitBeforeReturns =
    sales.excl - cost.excl - commission.excl - shipping.excl - service.excl - adAmount;

  // İade olursa: satış ve komisyon geri yazılır, ürün stoğa döner (satılamaz payı hariç);
  // gönderi kargo, iade kargo, hizmet bedeli ve reklam geri alınmaz (K10, G16, G17).
  // Kayıp farkı = (iade yoksa kâr) - (iade varsa kâr) = satış - komisyon - maliyet x (1 - satılamaz) + iade kargo.
  // Beklenen kayıp tek bir yuvarlamayla bulunur: kayıp x iade oranı.
  const lossNumerator =
    (sales.excl - commission.excl + returnShipping.excl - cost.excl) * 10000n +
    cost.excl * input.unsellableBps;
  const returnCost = divRound(lossNumerator * input.returnRateBps, 100000000n);

  const netProfit = profitBeforeReturns - returnCost;
  const marginBps = sales.excl > 0n ? divRound(netProfit * 10000n, sales.excl) : null;

  const vatEffect =
    sales.vat - (commission.vat + shipping.vat + service.vat + cost.vat + adSplit.vat);
  const withholding = percentOf(sales.excl, WITHHOLDING_BPS);

  return {
    sales,
    cost,
    commission,
    shipping,
    service,
    adAmount,
    profitBeforeReturns,
    returnCost,
    netProfit,
    marginBps,
    vatEffect,
    withholding,
    returnShipping,
  };
}

/** Net kârı verilen fiyatta hesaplar (başabaş araması için). */
function netProfitAt(input: ProfitInput, priceIncl: Kurus): Kurus {
  return core({ ...input, priceIncl }).netProfit;
}

/**
 * Beklenen net kâr, fiyata göre doğrusaldır:
 *   net(P) = P x D - F,   D = (1 - p) x a - reklam oranı,   F = sabit giderlerin beklenen toplamı
 * Önce kesirli çözüm bulunur, sonra kuruş yuvarlamaları için gerçek hesapla birkaç kuruş içinde
 * düzeltilir (net >= 0 olan en küçük kuruş).
 */
function findBreakEven(input: ProfitInput): Kurus | null {
  const p = R.frac(input.returnRateBps, 10000n);
  const s = R.frac(input.unsellableBps, 10000n);
  const c = R.frac(input.commissionBps, 10000n);

  const cost = splitCost(input).excl;
  const shipping = splitService(input.shipping, input.shippingIncludesVat).excl;
  const returnShipping = splitService(input.returnShipping, input.shippingIncludesVat).excl;
  const service = input.serviceFeeExcl;

  // a: KDV hariç satış payı - komisyon payı (KDV hariç)
  const salesShare = R.frac(100n, 100n + BigInt(input.vatRatePct));
  const commissionShare = input.commissionIncludesVat
    ? R.mul(c, R.frac(100n, 100n + BigInt(SERVICE_VAT_RATE)))
    : c;
  const a = R.sub(salesShare, commissionShare);

  const adRate = input.ad.kind === 'roas' ? R.frac(100n, input.ad.roasHundredths) : R.frac(0n);
  const adFixed = input.ad.kind === 'amount' ? input.ad.amount : 0n;

  const one = R.frac(1n);
  const notReturned = R.sub(one, p);
  const d = R.sub(R.mul(notReturned, a), adRate);
  if (!R.isPositive(d)) return null;

  const normalFixed = R.frac(cost + shipping + service);
  const returnFixed = R.add(R.frac(shipping + returnShipping + service), R.mul(s, R.frac(cost)));
  const fixed = R.add(
    R.add(R.mul(notReturned, normalFixed), R.mul(p, returnFixed)),
    R.frac(adFixed),
  );

  let price = R.ceil(R.div(fixed, d));
  if (price < 1n) price = 1n;
  // Yuvarlama düzeltmesi: net >= 0 olan en küçük kuruş
  for (let i = 0; i < 200 && netProfitAt(input, price) < 0n; i += 1) price += 1n;
  for (let i = 0; i < 200 && price > 1n && netProfitAt(input, price - 1n) >= 0n; i += 1) {
    price -= 1n;
  }
  return price;
}

export function calculateProfit(input: ProfitInput): ProfitResult {
  const c = core(input);

  // Başabaş ROAS (K25 / 06 belgesi): KDV hariç satış / reklam öncesi net kâr.
  const profitBeforeAd = c.netProfit + c.adAmount;
  const hasPositiveBase = profitBeforeAd > 0n && c.sales.excl > 0n;
  const breakEvenRoasExcl = hasPositiveBase ? divRound(c.sales.excl * 100n, profitBeforeAd) : null;
  const breakEvenRoasIncl = hasPositiveBase
    ? divRound(input.priceIncl * 100n, profitBeforeAd)
    : null;

  return {
    salesIncl: c.sales.incl,
    salesExcl: c.sales.excl,
    salesVat: c.sales.vat,
    cost: c.cost.excl,
    commissionExcl: c.commission.excl,
    commissionVat: c.commission.vat,
    shipping: c.shipping.excl,
    serviceFee: c.service.excl,
    ad: c.adAmount,
    profitBeforeReturns: c.profitBeforeReturns,
    returnCost: c.returnCost,
    netProfit: c.netProfit,
    marginBps: c.marginBps,
    vatEffect: c.vatEffect,
    withholding: c.withholding,
    breakEvenPrice: findBreakEven(input),
    breakEvenRoasExcl,
    breakEvenRoasIncl,
  };
}
