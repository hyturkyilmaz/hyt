// Backend sözleşmesi: services/api/app/api/v1/profit_settings.py ve profit_settings_schemas.py.
// Alan adları şemayla birebir aynıdır (gövdeler `extra="forbid"`: fazladan alan 422 döner).
// Para ve oranlar Decimal DİZGESİDİR ("45.00"); float'a çevrilmez. Girdide de dizge gönderilir.
import { ApiError, apiFetch } from '@/lib/api/client';

export type Money = string;

export type Agreement = 'trendyol' | 'seller';
export type ExpenseKind = 'siparis_basi' | 'adet_basi' | 'satis_yuzdesi';

/** `*`: "Diğer firmalar" yedek tarifesi (K34) */
export const OTHER_CARRIERS = '*';

export interface BracketOut {
  max_desi: Money;
  price: Money;
  price_excl_vat: Money;
}

export interface CargoTariffOut {
  id: string;
  agreement: Agreement;
  carrier: string;
  valid_from: string;
  price_includes_vat: boolean;
  brackets: BracketOut[];
}

export interface ServiceFeeOut {
  id: string;
  valid_from: string;
  amount: Money;
  amount_includes_vat: boolean;
  amount_excl_vat: Money;
}

export interface VariableExpenseOut {
  id: string;
  name: string;
  kind: ExpenseKind;
  amount_excl_vat: Money | null;
  percent: string | null;
  vat_rate: number;
  valid_from: string;
  valid_to: string | null;
}

export interface Completeness {
  cargo_tariff_defined: boolean;
  seller_cargo_tariff_defined: boolean;
  service_fee_estimate_defined: boolean;
  variable_expenses_defined: boolean;
  default_desi_defined: boolean;
}

export interface SettingsOut {
  revision: number;
  default_desi: Money | null;
  cargo_tariffs: CargoTariffOut[];
  service_fee_estimates: ServiceFeeOut[];
  variable_expenses: VariableExpenseOut[];
  completeness: Completeness;
}

export interface CarrierOut {
  carrier: string;
  agreement: Agreement;
  line_count: number;
  covered: boolean;
}

export interface CarriersOut {
  lookback_days: number;
  items: CarrierOut[];
}

export type WriteAction = 'created' | 'replaced' | 'retracted' | 'unchanged';

/** Her yazım yanıtının ortak alanları (K42, K43) */
export interface WriteInfo {
  revision: number;
  changed: boolean;
  action: WriteAction;
  replaced_id: string | null;
  affects_from: string | null;
  affects_past: boolean;
}

export interface TariffWriteOut extends WriteInfo {
  created: boolean;
  tariff: CargoTariffOut;
}

export interface ServiceFeeWriteOut extends WriteInfo {
  created: boolean;
  estimate: ServiceFeeOut;
}

export interface ExpenseWriteOut extends WriteInfo {
  expense: VariableExpenseOut;
}

export interface DefaultsOut extends WriteInfo {
  default_desi: Money | null;
}

export type DeleteOut = WriteInfo;

export type HistoryItemKind =
  'cargo_tariff' | 'service_fee_estimate' | 'variable_expense' | 'defaults' | 'tasima';
export type HistoryAction = 'ekle' | 'degistir' | 'geri_cek' | 'tasima';

export interface HistoryItemOut {
  revision: number;
  changed_at: string;
  changed_by: { user_id: string; role: string | null } | null;
  item: HistoryItemKind;
  action: HistoryAction;
  affects_from: string | null;
  affects_past: boolean;
  past_change_confirmed: boolean;
  record: CargoTariffOut | ServiceFeeOut | VariableExpenseOut | null;
  replaced_record: CargoTariffOut | ServiceFeeOut | VariableExpenseOut | null;
  default_desi_before: Money | null;
  default_desi_after: Money | null;
}

export interface HistoryOut {
  items: HistoryItemOut[];
  next_cursor: string | null;
}

// --------------------------------------------------------------------------- istek gövdeleri

/** K43 onayı: 409 gövdesindeki etki tarihi (YYYY-AA-GG), tarihsizde "all" */
export type ConfirmAffectsFrom = string;

interface WriteGuards {
  /** Beklenen ayar sürümü (iki yönetici aynı anda düzenlerse 409) */
  expected_revision?: number;
  confirm_affects_from?: ConfirmAffectsFrom;
}

export interface BracketIn {
  max_desi: string;
  price: string;
}

export interface CargoTariffIn extends WriteGuards {
  agreement: Agreement;
  carrier: string;
  valid_from: string;
  price_includes_vat: boolean;
  brackets: BracketIn[];
}

export interface ServiceFeeIn extends WriteGuards {
  valid_from: string;
  amount: string;
  amount_includes_vat: boolean;
}

export interface VariableExpenseIn extends WriteGuards {
  name: string;
  kind: ExpenseKind;
  amount_excl_vat: string | null;
  percent: string | null;
  vat_rate: number;
  valid_from: string;
  valid_to: string | null;
}

export interface DefaultsIn extends WriteGuards {
  default_desi: string | null;
}

export interface DeleteGuards {
  expected_revision?: number;
  confirm_affects_from?: ConfirmAffectsFrom;
}

function base(accountId: string): string {
  return `/marketplace-accounts/${encodeURIComponent(accountId)}/profit-settings`;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

function itemPath(accountId: string, collection: string, id: string): string {
  return `${base(accountId)}/${collection}/${encodeURIComponent(id)}`;
}

export const profitSettingsApi = {
  read: (accountId: string, signal?: AbortSignal) =>
    apiFetch<SettingsOut>(base(accountId), { signal }),

  carriers: (accountId: string, signal?: AbortSignal) =>
    apiFetch<CarriersOut>(`${base(accountId)}/carriers`, { signal }),

  history: (
    accountId: string,
    params: { limit?: number; cursor?: string | null },
    signal?: AbortSignal,
  ) => apiFetch<HistoryOut>(`${base(accountId)}/history${query(params)}`, { signal }),

  putCargoTariff: (accountId: string, body: CargoTariffIn) =>
    apiFetch<TariffWriteOut>(`${base(accountId)}/cargo-tariffs`, { method: 'PUT', body }),

  deleteCargoTariff: (accountId: string, id: string, guards: DeleteGuards) =>
    apiFetch<DeleteOut>(`${itemPath(accountId, 'cargo-tariffs', id)}${query({ ...guards })}`, {
      method: 'DELETE',
    }),

  putServiceFee: (accountId: string, body: ServiceFeeIn) =>
    apiFetch<ServiceFeeWriteOut>(`${base(accountId)}/service-fee-estimates`, {
      method: 'PUT',
      body,
    }),

  deleteServiceFee: (accountId: string, id: string, guards: DeleteGuards) =>
    apiFetch<DeleteOut>(
      `${itemPath(accountId, 'service-fee-estimates', id)}${query({ ...guards })}`,
      { method: 'DELETE' },
    ),

  createExpense: (accountId: string, body: VariableExpenseIn) =>
    apiFetch<ExpenseWriteOut>(`${base(accountId)}/variable-expenses`, { method: 'POST', body }),

  updateExpense: (accountId: string, id: string, body: VariableExpenseIn) =>
    apiFetch<ExpenseWriteOut>(itemPath(accountId, 'variable-expenses', id), {
      method: 'PUT',
      body,
    }),

  deleteExpense: (accountId: string, id: string, guards: DeleteGuards) =>
    apiFetch<DeleteOut>(`${itemPath(accountId, 'variable-expenses', id)}${query({ ...guards })}`, {
      method: 'DELETE',
    }),

  putDefaults: (accountId: string, body: DefaultsIn) =>
    apiFetch<DefaultsOut>(`${base(accountId)}/defaults`, { method: 'PUT', body }),
};

// --------------------------------------------------------------------------- 409 ayrıştırıcıları

export interface PastChangeUnconfirmed {
  /** Etki tarihi; null: tarihsiz (varsayılan desi) */
  affectsFrom: string | null;
  currentRevision: number | null;
}

/** 409 `settings-past-change-unconfirmed`: onay penceresi açılır (K43, YT-07) */
export function asPastChangeUnconfirmed(error: unknown): PastChangeUnconfirmed | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (error.code !== 'settings-past-change-unconfirmed') return null;
  return {
    affectsFrom: error.details?.affects_from ?? null,
    currentRevision: error.details?.current_revision ?? null,
  };
}

/** 409 `settings-record-ended`: kayıt başka değişiklikle kapanmış; ekran yenilenir */
export function isRecordEnded(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 409 && error.code === 'settings-record-ended'
  );
}

/** 409 `settings-revision-conflict`: ayarlar araya giren başka bir yazımla değişmiş */
export function isRevisionConflict(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 409 && error.code === 'settings-revision-conflict'
  );
}
