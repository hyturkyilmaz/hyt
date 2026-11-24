import { screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { makeSettings, makeSettingsWithServerFacts } from '@/lib/profit/settings-fixtures';
import { addDays, todayIstanbul } from '@/lib/profit/settings-input';
import { renderPanel } from '@/test/settings-panel-harness';

// Takvime bağlı beklentiler bugünden hesaplanır; sabit tarih yok.
const DEVICE_TODAY = todayIstanbul();

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openTariffForm(user: Awaited<ReturnType<typeof renderPanel>>['user']) {
  await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
  return screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
}

describe('Kâr ayarları formu, sunucu bilgileri', () => {
  it('başlangıç önerisi en eski sipariş gününden 1 gün öncedir ve "yaklaşık" notu çıkmaz', async () => {
    const earliest = addDays(DEVICE_TODAY, -300);
    const { user } = await renderPanel(
      {},
      makeSettingsWithServerFacts({ earliest_order_day: earliest, today_istanbul: DEVICE_TODAY }),
    );
    const form = await openTariffForm(user);
    expect(within(form).getByLabelText('Başlangıç tarihi')).toHaveValue(addDays(earliest, -1));
    expect(within(form).queryByText(/yaklaşıktır/)).not.toBeInTheDocument();
    expect(within(form).getByText(/en eski siparişten/)).toBeInTheDocument();
  });

  it('sipariş yoksa (null) yaklaşık öneri ve not kalır', async () => {
    const { user } = await renderPanel(
      {},
      makeSettingsWithServerFacts({ earliest_order_day: null, today_istanbul: DEVICE_TODAY }),
    );
    const form = await openTariffForm(user);
    expect(within(form).getByLabelText('Başlangıç tarihi')).toHaveValue(addDays(DEVICE_TODAY, -92));
    expect(within(form).getByText(/Önerilen tarih yaklaşıktır/)).toBeInTheDocument();
  });

  it('eski API (alanlar yok): yaklaşık öneri, cihaz günü ve %20', async () => {
    const { user } = await renderPanel({}, makeSettings());
    const form = await openTariffForm(user);
    expect(within(form).getByLabelText('Başlangıç tarihi')).toHaveValue(addDays(DEVICE_TODAY, -92));
    expect(within(form).getByText(/Önerilen tarih yaklaşıktır/)).toBeInTheDocument();
    expect(within(form).getByText('Kargo KDV oranı %20.')).toBeInTheDocument();
  });

  it('"bugün" sunucunun günüdür (cihaz saatinden bağımsız)', async () => {
    // Sunucu günü cihaz gününden farklıysa öneri sunucu gününe göre hesaplanır.
    const serverToday = addDays(DEVICE_TODAY, 5);
    const { user } = await renderPanel(
      {},
      makeSettingsWithServerFacts({ earliest_order_day: null, today_istanbul: serverToday }),
    );
    const form = await openTariffForm(user);
    expect(within(form).getByLabelText('Başlangıç tarihi')).toHaveValue(addDays(serverToday, -92));
  });

  it('KDV hariç karşılık sunucudaki orandan hesaplanır (kargo ve hizmet bedeli ayrı)', async () => {
    const { user } = await renderPanel(
      {},
      makeSettingsWithServerFacts({
        earliest_order_day: null,
        today_istanbul: DEVICE_TODAY,
        shipping: '10',
        service_fee: '0.5',
      }),
    );
    const form = await openTariffForm(user);
    expect(within(form).getByText('Kargo KDV oranı %10.')).toBeInTheDocument();
    const price = within(form).getByLabelText(/1\. kademe fiyatı/);
    await user.type(price, '55,00');
    // 55,00 / 1,10 = 50,00
    expect(
      within(form).getByText('Kaydedilecek: 55,00 TL KDV dahil = 50,00 TL KDV hariç'),
    ).toBeInTheDocument();
    await user.click(within(form).getByRole('button', { name: 'Vazgeç' }));

    await user.click(screen.getByRole('button', { name: 'Tahmin ekle' }));
    const feeForm = await screen.findByRole('form', { name: /hizmet bedeli/i });
    expect(within(feeForm).getByText('Hizmet bedeli KDV oranı %0,5.')).toBeInTheDocument();
    await user.type(within(feeForm).getByLabelText(/Sipariş başına tutar/), '10,05');
    // 10,05 / 1,005 = 10,00
    expect(
      within(feeForm).getByText('Kaydedilecek: 10,05 TL KDV dahil = 10,00 TL KDV hariç'),
    ).toBeInTheDocument();
  });
});
