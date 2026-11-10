// Ayar ekranı sunum kuralları (ADR-0007 §5.2 ayar ekranı, UX incelemesi §8.1, denetim §7 madde 8).
// Saf fonksiyonlar: bileşenler yalnız bu çıktıyı çizer; metinler testle korunur.
import type {
  Agreement,
  CargoTariffOut,
  Completeness,
  ExpenseKind,
  HistoryItemOut,
  ServiceFeeOut,
  VariableExpenseOut,
} from '@/lib/api/profit-settings';
import { OTHER_CARRIERS } from '@/lib/api/profit-settings';
import { compareDecimal, decimalSign } from '@/lib/profit/decimal-math';
import {
  formatDateTime,
  formatDesi,
  formatLongDate,
  formatPlainNumber,
} from '@/lib/profit/settings-input';
import { formatTRY } from '@/lib/format';

export const AGREEMENT_LABELS: Record<Agreement, string> = {
  trendyol: 'Trendyol anlaşmalı',
  seller: 'Kendi kargo anlaşmam',
};

export const EXPENSE_KIND_LABELS: Record<ExpenseKind, string> = {
  siparis_basi: 'Sipariş başına',
  adet_basi: 'Adet başına',
  satis_yuzdesi: 'Satış yüzdesi',
};

const ROLE_LABELS: Record<string, string> = {
  owner: 'Sahip',
  admin: 'Yönetici',
  viewer: 'Görüntüleyici',
};

/** `*` yedeği "Diğer firmalar" olarak; boş ad (siparişte firma yok) aynı yedeğe eşlenir (AB-04). */
export function carrierLabel(carrier: string): string {
  return carrier === OTHER_CARRIERS || carrier === '' ? 'Diğer firmalar' : carrier;
}

/** /carriers boş adı `*` önerisine eşler; formda tek geçerli değer budur (AB-04). */
export function carrierValue(carrier: string): string {
  return carrier === '' ? OTHER_CARRIERS : carrier;
}

export function isZeroAmount(value: string): boolean {
  return decimalSign(value) === 0;
}

// --------------------------------------------------------------------------- tamamlama

export interface SetupStep {
  id: 'kargo' | 'hizmet-bedeli';
  label: string;
  done: boolean;
}

/** UX §8.1: ilerleme göstergesi. `completeness` yalnız bu ekranda "bugün geçerli" anlamıyla kullanılır (§7.3). */
export function setupSteps(completeness: Completeness): SetupStep[] {
  return [
    { id: 'kargo', label: 'Kargo tarifesi', done: completeness.cargo_tariff_defined },
    {
      id: 'hizmet-bedeli',
      label: 'Hizmet bedeli',
      done: completeness.service_fee_estimate_defined,
    },
  ];
}

export function setupProgressText(steps: readonly SetupStep[]): string {
  const done = steps.filter((s) => s.done).length;
  // Tamlama eki sayının okunuşuna göre değişir: sıfır -> 0'ı, bir -> 1'i, iki -> 2'si (adım sayısı en çok iki)
  const suffix: Record<number, string> = { 0: "'ı", 1: "'i", 2: "'si" };
  const tail = suffix[done];
  return tail
    ? `${steps.length} adımdan ${done}${tail} tamam`
    : `${steps.length} adımdan ${done} tamam`;
}

// --------------------------------------------------------------------------- onay penceresi (ADR-0007 §5.2 madde 1)

export type ConfirmTopic = 'dated' | 'defaults' | 'retract-cargo' | 'retract-other';

export interface ConfirmCopy {
  title: string;
  body: string;
}

/**
 * Onay penceresi metinleri ADR-0007 §5.2'den BİREBİR: başlık "Geçmiş raporlar değişecek".
 * Geri çekmede kargo metni ADR'dedir; ADR'nin tanımlamadığı geri çekmelerde (hizmet bedeli, gider) tarihli genel
 * metin kullanılır.
 */
export function confirmCopy(topic: ConfirmTopic, affectsFrom: string | null): ConfirmCopy {
  const title = 'Geçmiş raporlar değişecek';
  if (topic === 'defaults' || affectsFrom === null) {
    return {
      title,
      body: 'Siparişinde desi bilgisi olmayan tüm geçmiş siparişlerin kargo tahmini değişir.',
    };
  }
  const date = formatLongDate(affectsFrom);
  if (topic === 'retract-cargo') {
    return {
      title,
      body: `Bu sürüm geri çekilirse ${date} sonrası siparişlerde kargo önceki sürümden ya da 'diğer firmalar' tarifesinden hesaplanır; hiçbiri yoksa kargo 'eksik' görünür ve net kâr hesaplanamaz.`,
    };
  }
  return {
    title,
    body: `Bu değişiklik ${date} ve sonrasındaki siparişlerin kâr hesabını değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki değer ayar geçmişinde saklanır.`,
  };
}

// --------------------------------------------------------------------------- liste özetleri

/** "54,00 TL KDV dahil = 45,00 TL KDV hariç" (UX §8.1); hariç girişte yalnız hariç tutar. */
export function vatPair(entered: string, excl: string, includesVat: boolean): string {
  if (!includesVat) return `${formatTRY(entered, { style: 'code' })} KDV hariç`;
  return `${formatTRY(entered, { style: 'code' })} KDV dahil = ${formatTRY(excl, { style: 'code' })} KDV hariç`;
}

export function describeExpenseAmount(expense: VariableExpenseOut): string {
  if (expense.kind === 'satis_yuzdesi') {
    return `Satış tutarının %${formatPlainNumber(expense.percent ?? '0', 4)}`;
  }
  const amount = formatTRY(expense.amount_excl_vat ?? '0', { style: 'code' });
  const unit = expense.kind === 'adet_basi' ? 'Adet başına' : 'Sipariş başına';
  return `${unit} ${amount} (KDV hariç)`;
}

export function describeValidity(from: string, to: string | null): string {
  return to
    ? `${formatLongDate(from)} ile ${formatLongDate(to)} arası`
    : `${formatLongDate(from)} tarihinden itibaren`;
}

// --------------------------------------------------------------------------- ayar geçmişi

export type HistoryRecord = CargoTariffOut | ServiceFeeOut | VariableExpenseOut;

export interface HistoryBadge {
  label: string;
  tone: 'neutral' | 'warning' | 'info';
}

export interface HistoryEntryView {
  key: string;
  /** "10 Kasım 2026, 14:35" */
  when: string;
  /** "Yönetici" gibi rol; ad ve e-posta tutulmaz (ADR-0007 Revizyon 1 YT-08) */
  who: string;
  /** "Trendyol Express tarifesi (başlangıç 1 Ekim 2026) değiştirildi" */
  headline: string;
  /** Fark satırları: "2 desi 54,00 → 60,00 (KDV dahil)" */
  details: string[];
  badges: HistoryBadge[];
}

function whoLabel(entry: HistoryItemOut): string {
  if (entry.changed_by === null) return 'Silinmiş kullanıcı';
  const role = entry.changed_by.role;
  return role ? (ROLE_LABELS[role] ?? 'Kullanıcı') : 'Eski kullanıcı';
}

const ACTION_VERB: Record<string, string> = {
  ekle: 'eklendi',
  degistir: 'değiştirildi',
  geri_cek: 'geri çekildi',
};

function isTariff(record: HistoryRecord): record is CargoTariffOut {
  return 'brackets' in record;
}

function isFee(record: HistoryRecord): record is ServiceFeeOut {
  return 'amount_includes_vat' in record;
}

function isExpense(record: HistoryRecord): record is VariableExpenseOut {
  return 'kind' in record;
}

function vatWord(includes: boolean): string {
  return includes ? 'KDV dahil' : 'KDV hariç';
}

function tariffSubject(record: CargoTariffOut): string {
  const where =
    record.agreement === 'seller'
      ? `kendi anlaşmanız, başlangıç ${formatLongDate(record.valid_from)}`
      : `başlangıç ${formatLongDate(record.valid_from)}`;
  return `${carrierLabel(record.carrier)} tarifesi (${where})`;
}

function tariffDiff(before: CargoTariffOut, after: CargoTariffOut): string[] {
  const lines: string[] = [];
  if (before.price_includes_vat !== after.price_includes_vat) {
    lines.push(
      `Giriş biçimi ${vatWord(before.price_includes_vat)} yerine ${vatWord(after.price_includes_vat)} oldu`,
    );
  }
  const suffix = `(${vatWord(after.price_includes_vat)})`;
  for (const next of after.brackets) {
    const previous = before.brackets.find((b) => compareDecimal(b.max_desi, next.max_desi) === 0);
    if (!previous) {
      lines.push(
        `${formatDesi(next.max_desi)} desi kademesi eklendi: ${formatPlainNumber(next.price, 2, 2)} ${suffix}`,
      );
    } else if (compareDecimal(previous.price, next.price) !== 0) {
      lines.push(
        `${formatDesi(next.max_desi)} desi ${formatPlainNumber(previous.price, 2, 2)} → ${formatPlainNumber(next.price, 2, 2)} ${suffix}`,
      );
    }
  }
  for (const previous of before.brackets) {
    if (!after.brackets.some((b) => compareDecimal(b.max_desi, previous.max_desi) === 0)) {
      lines.push(`${formatDesi(previous.max_desi)} desi kademesi kaldırıldı`);
    }
  }
  return lines;
}

function feeDiff(before: ServiceFeeOut, after: ServiceFeeOut): string[] {
  const lines: string[] = [];
  if (
    compareDecimal(before.amount, after.amount) !== 0 ||
    before.amount_includes_vat !== after.amount_includes_vat
  ) {
    const from = `${formatPlainNumber(before.amount, 2, 2)} ${vatWord(before.amount_includes_vat)}`;
    const to = `${formatPlainNumber(after.amount, 2, 2)} ${vatWord(after.amount_includes_vat)}`;
    lines.push(`${from} → ${to}`);
  }
  return lines;
}

function expenseDiff(before: VariableExpenseOut, after: VariableExpenseOut): string[] {
  const lines: string[] = [];
  if (before.name !== after.name) lines.push(`Ad: ${before.name} → ${after.name}`);
  if (before.kind !== after.kind) {
    lines.push(`Tür: ${EXPENSE_KIND_LABELS[before.kind]} → ${EXPENSE_KIND_LABELS[after.kind]}`);
  }
  const beforeAmount = describeExpenseAmount(before);
  const afterAmount = describeExpenseAmount(after);
  if (beforeAmount !== afterAmount && before.kind === after.kind) {
    lines.push(`${beforeAmount} → ${afterAmount}`);
  } else if (before.kind !== after.kind) {
    lines.push(`${afterAmount}`);
  }
  if (before.vat_rate !== after.vat_rate)
    lines.push(`KDV oranı %${before.vat_rate} → %${after.vat_rate}`);
  if (before.valid_from !== after.valid_from) {
    lines.push(
      `Başlangıç: ${formatLongDate(before.valid_from)} → ${formatLongDate(after.valid_from)}`,
    );
  }
  if (before.valid_to !== after.valid_to) {
    const from = before.valid_to ? formatLongDate(before.valid_to) : 'süresiz';
    const to = after.valid_to ? formatLongDate(after.valid_to) : 'süresiz';
    lines.push(`Bitiş: ${from} → ${to}`);
  }
  return lines;
}

function createdSummary(record: HistoryRecord): string[] {
  if (isTariff(record)) {
    const zero = record.brackets.some((b) => isZeroAmount(b.price));
    const count = record.brackets.length;
    const lines = [`${count} kademe (${vatWord(record.price_includes_vat)})`];
    if (zero) lines.push('0 girildi');
    return lines;
  }
  if (isFee(record)) {
    const lines = [
      `${formatPlainNumber(record.amount, 2, 2)} TL (${vatWord(record.amount_includes_vat)})`,
    ];
    if (isZeroAmount(record.amount)) lines.push('0 girildi');
    return lines;
  }
  return [describeExpenseAmount(record), `KDV oranı %${record.vat_rate}`];
}

function subjectOf(entry: HistoryItemOut): string {
  const record = entry.record ?? entry.replaced_record;
  if (entry.item === 'defaults') return 'Varsayılan desi';
  if (!record) return 'Ayar';
  if (isTariff(record)) return tariffSubject(record);
  if (isFee(record))
    return `Hizmet bedeli tahmini (başlangıç ${formatLongDate(record.valid_from)})`;
  if (isExpense(record))
    return `${record.name} gideri (başlangıç ${formatLongDate(record.valid_from)})`;
  return 'Ayar';
}

function badgesOf(entry: HistoryItemOut): HistoryBadge[] {
  const badges: HistoryBadge[] = [];
  if (entry.action === 'geri_cek') badges.push({ label: 'Geri çekildi', tone: 'neutral' });
  if (entry.affects_past && entry.past_change_confirmed) {
    badges.push({ label: 'Geçmişi etkiledi (onaylı)', tone: 'warning' });
  }
  return badges;
}

/** Ayar günlüğü kaydı -> okunur cümle ve fark satırları (ADR-0007 §5.2 madde 2). */
export function historyEntryView(entry: HistoryItemOut): HistoryEntryView {
  const when = formatDateTime(entry.changed_at);
  const who = whoLabel(entry);
  const key = `${entry.revision}-${entry.item}`;
  const badges = badgesOf(entry);

  if (entry.item === 'tasima') {
    return {
      key,
      when,
      who,
      headline: 'Ayarlar sürüm geçmişi düzenine taşındı',
      details: [],
      badges,
    };
  }

  const verb = ACTION_VERB[entry.action] ?? 'güncellendi';
  const headline = `${subjectOf(entry)} ${verb}`;

  let details: string[] = [];
  if (entry.item === 'defaults') {
    const before =
      entry.default_desi_before === null ? 'tanımsız' : formatDesi(entry.default_desi_before);
    const after =
      entry.default_desi_after === null ? 'tanımsız' : formatDesi(entry.default_desi_after);
    details = [`${before} → ${after}`];
  } else if (entry.action === 'ekle' && entry.record) {
    details = createdSummary(entry.record);
  } else if (entry.action === 'degistir' && entry.record && entry.replaced_record) {
    const next = entry.record;
    const previous = entry.replaced_record;
    if (isTariff(next) && isTariff(previous)) details = tariffDiff(previous, next);
    else if (isFee(next) && isFee(previous)) details = feeDiff(previous, next);
    else if (isExpense(next) && isExpense(previous)) details = expenseDiff(previous, next);
  }
  return { key, when, who, headline, details, badges };
}
