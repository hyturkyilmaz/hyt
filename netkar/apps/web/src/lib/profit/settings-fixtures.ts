// Test ve e2e için kâr ayarları API örnek yanıtları (alan adları services/api profit_settings_schemas.py ile aynı).
// Üretim kodunda kullanılmaz. Yalnız tür içe aktarımı yapılır: Playwright de bu dosyayı doğrudan yükler.
import type {
  CargoTariffOut,
  CarriersOut,
  Completeness,
  HistoryItemOut,
  HistoryOut,
  ServiceFeeOut,
  SettingsOut,
  VariableExpenseOut,
  WriteInfo,
} from '../api/profit-settings';

export const TARIFF_ID = '22222222-2222-4222-8222-222222222222';
export const FEE_ID = '33333333-3333-4333-8333-333333333333';
export const EXPENSE_ID = '44444444-4444-4444-8444-444444444444';

export function makeTariff(over: Partial<CargoTariffOut> = {}): CargoTariffOut {
  return {
    id: TARIFF_ID,
    agreement: 'trendyol',
    carrier: 'Trendyol Express',
    valid_from: '2026-10-01',
    price_includes_vat: true,
    brackets: [
      { max_desi: '2.00', price: '54.00', price_excl_vat: '45.00' },
      { max_desi: '5.00', price: '72.00', price_excl_vat: '60.00' },
    ],
    ...over,
  };
}

export function makeFee(over: Partial<ServiceFeeOut> = {}): ServiceFeeOut {
  return {
    id: FEE_ID,
    valid_from: '2026-10-01',
    amount: '12.00',
    amount_includes_vat: true,
    amount_excl_vat: '10.00',
    ...over,
  };
}

export function makeExpense(over: Partial<VariableExpenseOut> = {}): VariableExpenseOut {
  return {
    id: EXPENSE_ID,
    name: 'Paketleme',
    kind: 'siparis_basi',
    amount_excl_vat: '6.50',
    percent: null,
    vat_rate: 20,
    valid_from: '2026-10-01',
    valid_to: null,
    ...over,
  };
}

export function makeCompleteness(over: Partial<Completeness> = {}): Completeness {
  return {
    cargo_tariff_defined: true,
    seller_cargo_tariff_defined: false,
    service_fee_estimate_defined: true,
    variable_expenses_defined: true,
    default_desi_defined: true,
    ...over,
  };
}

export function makeSettings(over: Partial<SettingsOut> = {}): SettingsOut {
  return {
    revision: 7,
    default_desi: '3.00',
    cargo_tariffs: [makeTariff()],
    service_fee_estimates: [makeFee()],
    variable_expenses: [makeExpense()],
    completeness: makeCompleteness(),
    ...over,
  };
}

/** Hiç ayar girilmemiş hesap (ilk giriş): her şey boş, tamlık bayrakları yanlış */
export function makeEmptySettings(over: Partial<SettingsOut> = {}): SettingsOut {
  return makeSettings({
    revision: 0,
    default_desi: null,
    cargo_tariffs: [],
    service_fee_estimates: [],
    variable_expenses: [],
    completeness: makeCompleteness({
      cargo_tariff_defined: false,
      service_fee_estimate_defined: false,
      variable_expenses_defined: false,
      default_desi_defined: false,
    }),
    ...over,
  });
}

export function makeCarriers(over: Partial<CarriersOut> = {}): CarriersOut {
  return {
    lookback_days: 92,
    items: [
      { carrier: 'Trendyol Express', agreement: 'trendyol', line_count: 120, covered: true },
      { carrier: 'Yurtiçi Kargo', agreement: 'trendyol', line_count: 34, covered: false },
      { carrier: '', agreement: 'trendyol', line_count: 3, covered: false },
      { carrier: 'Kendi Kuryem', agreement: 'seller', line_count: 8, covered: false },
    ],
    ...over,
  };
}

export function makeWriteInfo(over: Partial<WriteInfo> = {}): WriteInfo {
  return {
    revision: 8,
    changed: true,
    action: 'created',
    replaced_id: null,
    affects_from: null,
    affects_past: false,
    ...over,
  };
}

export function makeHistoryItem(over: Partial<HistoryItemOut> = {}): HistoryItemOut {
  return {
    revision: 7,
    changed_at: '2026-11-10T11:35:00Z',
    changed_by: { user_id: '00000000-0000-4000-8000-000000000001', role: 'admin' },
    item: 'cargo_tariff',
    action: 'degistir',
    affects_from: '2026-10-01',
    affects_past: true,
    past_change_confirmed: true,
    record: makeTariff({
      brackets: [
        { max_desi: '2.00', price: '60.00', price_excl_vat: '50.00' },
        { max_desi: '5.00', price: '72.00', price_excl_vat: '60.00' },
      ],
    }),
    replaced_record: makeTariff(),
    default_desi_before: null,
    default_desi_after: null,
    ...over,
  };
}

export function makeHistory(
  items: HistoryItemOut[] = [makeHistoryItem()],
  over: Partial<HistoryOut> = {},
): HistoryOut {
  return { items, next_cursor: null, ...over };
}
