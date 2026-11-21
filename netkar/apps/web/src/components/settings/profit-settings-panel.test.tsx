import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProfitSettingsPanel } from '@/components/settings/profit-settings-panel';
import { addDays, todayIstanbul } from '@/lib/profit/settings-input';
import {
  EXPENSE_ID,
  FEE_ID,
  TARIFF_ID,
  makeCarriers,
  makeEmptySettings,
  makeExpense,
  makeFee,
  makeHistory,
  makeHistoryItem,
  makeSettings,
  makeTariff,
  makeWriteInfo,
} from '@/lib/profit/settings-fixtures';
import { ACCOUNT_ID } from '@/lib/profit/test-fixtures';
import {
  installFakeApi,
  problemBody,
  type RecordedCall,
  type Responder,
} from '@/test/settings-api-mock';

const BASE = `/marketplace-accounts/${ACCOUNT_ID}/profit-settings`;
const TODAY = todayIstanbul();

afterEach(() => {
  vi.unstubAllGlobals();
});

type Routes = Record<string, Responder | { status?: number; body?: unknown }>;

function routes(over: Routes = {}, settings = makeSettings()): Routes {
  return {
    [`GET ${BASE}`]: { body: settings },
    [`GET ${BASE}/carriers`]: { body: makeCarriers() },
    [`GET ${BASE}/history`]: { body: makeHistory() },
    'GET /me': { body: { role: 'owner' } },
    ...over,
  };
}

async function renderPanel(over: Routes = {}, settings = makeSettings()) {
  const api = installFakeApi(routes(over, settings));
  const user = userEvent.setup();
  render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
  await screen.findByRole('heading', { name: 'Kargo tarifesi' });
  // Rol (/me) yüklenene kadar yazma düğmeleri yoktur (AF-10)
  await screen.findByRole('button', { name: 'Tarife ekle' });
  return { api, user };
}

describe('Kâr ayarları paneli, durumlar', () => {
  it('yüklenirken yükleniyor duyurur', () => {
    installFakeApi({ [`GET ${BASE}`]: () => new Promise(() => undefined) });
    render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
    expect(screen.getByRole('status')).toHaveTextContent('Yükleniyor');
  });

  it('hata durumunda ayrıntısız mesaj ve tekrar dene', async () => {
    let fail = true;
    const api = installFakeApi(
      routes({
        [`GET ${BASE}`]: () =>
          fail ? { status: 503, body: problemBody('busy') } : { body: makeSettings() },
      }),
    );
    const user = userEvent.setup();
    render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Kâr ayarları yüklenemedi');
    expect(alert).toHaveTextContent('Rapor şu an yoğun');
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(await screen.findByRole('heading', { name: 'Kargo tarifesi' })).toBeInTheDocument();
    expect(api.count('GET', BASE)).toBe(2);
  });

  it('hiç ayar yoksa boş durumlar, eksik rozetleri ve 0 adım tamam', async () => {
    await renderPanel({}, makeEmptySettings());
    expect(screen.getByText("2 adımdan 0'ı tamam")).toBeInTheDocument();
    expect(screen.getByText(/Henüz kargo tarifesi girmediniz/)).toBeInTheDocument();
    expect(screen.getByText(/Henüz hizmet bedeli tahmini girmediniz/)).toBeInTheDocument();
    expect(screen.getByText('Henüz değişken gider girmediniz.')).toBeInTheDocument();
    expect(screen.getByText('Bugün geçerli tarife yok')).toBeInTheDocument();
    expect(screen.getByText('Tanımsız')).toBeInTheDocument();
  });

  it('dolu ayarlar: KDV dahil ve hariç karşılığı birlikte, bölümler ve sürüm', async () => {
    await renderPanel();
    expect(screen.getByText("2 adımdan 2'si tamam")).toBeInTheDocument();
    const tariff = screen.getByRole('table', { name: /Trendyol Express desi kademeleri/ });
    expect(tariff).toHaveTextContent('54,00 TL KDV dahil = 45,00 TL KDV hariç');
    expect(tariff).toHaveTextContent('72,00 TL KDV dahil = 60,00 TL KDV hariç');
    expect(screen.getByText('KDV dahil girildi')).toBeInTheDocument();
    expect(screen.getByText('12,00 TL KDV dahil = 10,00 TL KDV hariç')).toBeInTheDocument();
    expect(screen.getByText('3 desi')).toBeInTheDocument();
    expect(screen.getByText('Paketleme')).toBeInTheDocument();
    expect(screen.getAllByText('Ayar sürümü 7').length).toBeGreaterThan(0);
    // Başlangıç tarihi metni
    expect(
      screen.getAllByText(/Bu tarihten sonraki siparişlerde kullanılır/).length,
    ).toBeGreaterThan(0);
  });

  it('0 girilen kalemler "0 girildi" rozeti alır (AB-07)', async () => {
    await renderPanel(
      {},
      makeSettings({
        cargo_tariffs: [
          makeTariff({
            brackets: [{ max_desi: '1000.00', price: '0.00', price_excl_vat: '0.00' }],
          }),
        ],
        service_fee_estimates: [makeFee({ amount: '0.00', amount_excl_vat: '0.00' })],
      }),
    );
    expect(screen.getAllByText('0 girildi')).toHaveLength(2);
  });

  it('görüntüleyici yalnız okur: ekleme ve düzenleme düğmesi yok', async () => {
    const api = installFakeApi(routes({ 'GET /me': { body: { role: 'viewer' } } }));
    render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
    await screen.findByText(/Ayarları görüntüleyebilirsiniz/);
    expect(screen.queryByRole('button', { name: 'Tarife ekle' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Düzenle/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Geri çek/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('form', { name: 'Varsayılan desi' })).not.toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });
});

describe('Kargo tarifesi', () => {
  async function fillFirstTariff(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
    // Firma yalnız /carriers listesinden ve "Diğer firmalar" yedeğiyle
    const select = within(form).getByLabelText('Kargo firması');
    const labels = within(select as HTMLElement)
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(labels).toEqual([
      'Firma seçin',
      'Trendyol Express (son 92 günde 120 satır)',
      'Yurtiçi Kargo (son 92 günde 34 satır, tarifesi yok)',
      'Diğer firmalar (listede olmayan her firma)',
    ]);
    await user.selectOptions(select, 'Yurtiçi Kargo');
    await user.type(within(form).getByLabelText('1. kademe, en çok desi'), '2');
    await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '54');
    return form;
  }

  it('KDV hariç karşılığı yazarken Decimal ile gösterilir', async () => {
    const { user } = await renderPanel({}, makeEmptySettings());
    const form = await fillFirstTariff(user);
    expect(
      within(form).getByText('Kaydedilecek: 54,00 TL KDV dahil = 45,00 TL KDV hariç'),
    ).toBeInTheDocument();
    await user.clear(within(form).getByLabelText(/1\. kademe fiyatı/));
    await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '50,00');
    expect(
      within(form).getByText('Kaydedilecek: 50,00 TL KDV dahil = 41,67 TL KDV hariç'),
    ).toBeInTheDocument();
    await user.clear(within(form).getByLabelText(/1\. kademe fiyatı/));
    await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '0');
    expect(within(form).getByText('0 girildi')).toBeInTheDocument();
    // KDV hariç girişte hariç karşılığı yok ama ayrıştırılan değer yine yansır (AF-01)
    await user.clear(within(form).getByLabelText(/1\. kademe fiyatı/));
    await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '12,55');
    await user.click(within(form).getByRole('radio', { name: /^KDV hariç/ }));
    expect(within(form).queryByText(/KDV dahil =/)).not.toBeInTheDocument();
    expect(within(form).getByText('Kaydedilecek: 12,55 TL KDV hariç')).toBeInTheDocument();
  });

  it('ilk giriş: onaysız gönderilir, expected_revision gider, başarı bildirimi ve yenileme', async () => {
    let saved = false;
    const { api, user } = await renderPanel(
      {
        [`GET ${BASE}`]: () => ({
          body: saved
            ? makeSettings({
                revision: 1,
                cargo_tariffs: [makeTariff({ carrier: 'Yurtiçi Kargo' })],
              })
            : makeEmptySettings(),
        }),
        [`PUT ${BASE}/cargo-tariffs`]: () => {
          saved = true;
          return {
            body: {
              ...makeWriteInfo({ revision: 1, affects_past: true }),
              created: true,
              tariff: makeTariff({ carrier: 'Yurtiçi Kargo' }),
            },
          };
        },
      },
      makeEmptySettings(),
    );
    await fillFirstTariff(user);
    await user.click(screen.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));

    expect(await screen.findByText(/Tarife eklendi/)).toBeInTheDocument();
    const put = api.writes()[0] as RecordedCall;
    expect(put.method).toBe('PUT');
    expect(put.path).toBe(`${BASE}/cargo-tariffs`);
    expect(put.body).toMatchObject({
      agreement: 'trendyol',
      carrier: 'Yurtiçi Kargo',
      price_includes_vat: true,
      brackets: [{ max_desi: '2', price: '54.00' }],
      expected_revision: 0,
    });
    // İlk giriş istisnası: onay gönderilmez (gönderilmiş eşleşmeyen onay 409 üretirdi)
    expect(put.body).not.toHaveProperty('confirm_affects_from');
    expect(put.body).not.toHaveProperty('confirm_past_change');
    expect(api.writes()).toHaveLength(1);
    // Form kapandı, liste yenilendi
    expect(screen.queryByRole('form', { name: 'Yeni kargo tarifesi' })).not.toBeInTheDocument();
    expect(await screen.findByText('Yurtiçi Kargo')).toBeInTheDocument();
  });

  const unconfirmed = {
    status: 409,
    body: problemBody('settings-past-change-unconfirmed', {
      affects_from: '2026-08-10',
      affects_past: true,
      current_revision: 9,
    }),
  };

  it('409: onay penceresi ADR metniyle açılır; onaylayınca etki tarihi ve 409 sürümü geri gönderilir', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        if (attempt === 1) return unconfirmed;
        return {
          body: {
            ...makeWriteInfo({ revision: 10, affects_past: true }),
            created: true,
            tariff: makeTariff(),
          },
        };
      },
    });
    await fillFirstTariff(user);
    await user.click(screen.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));

    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(dialog).toHaveTextContent(
      'Bu değişiklik 10 Ağustos 2026 ve sonrasındaki siparişlerin kâr hesabını değiştirir. Daha önce indirdiğiniz ya da paylaştığınız raporlardaki rakamlar artık farklı olabilir. Önceki değer ayar geçmişinde saklanır.',
    );
    expect(api.writes()).toHaveLength(1);

    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText(/Tarife eklendi/)).toBeInTheDocument();
    const second = api.writes()[1] as RecordedCall;
    expect(second.body).toMatchObject({
      confirm_affects_from: '2026-08-10',
      expected_revision: 9,
      // Form varsayılanı İstanbul'da bugün eksi 92 gün (lookback_days); sabit tarih her gün kırılırdı.
      valid_from: addDays(TODAY, -92),
    });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('409: vazgeçince hiçbir şey gönderilmez ve form açık kalır', async () => {
    const { api, user } = await renderPanel({ [`PUT ${BASE}/cargo-tariffs`]: unconfirmed });
    await fillFirstTariff(user);
    await user.click(screen.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(within(dialog).getByRole('button', { name: 'Vazgeç' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(api.writes()).toHaveLength(1);
    expect(screen.getByRole('form', { name: 'Yeni kargo tarifesi' })).toBeInTheDocument();
  });

  it('409: "Yalnız bugünden itibaren uygula" başlangıcı bugün olan sürümü onaysız gönderir', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        if (attempt === 1) return unconfirmed;
        return {
          body: {
            ...makeWriteInfo({ revision: 10 }),
            created: true,
            tariff: makeTariff({ valid_from: TODAY }),
          },
        };
      },
    });
    await fillFirstTariff(user);
    await user.click(screen.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(
      within(dialog).getByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    );
    expect(await screen.findByText(/Tarife eklendi/)).toBeInTheDocument();
    const second = api.writes()[1] as RecordedCall;
    expect(second.body).toMatchObject({ valid_from: TODAY, expected_revision: 9 });
    expect(second.body).not.toHaveProperty('confirm_affects_from');
  });

  it('422: sunucu alan hatası alanın yanında gösterilir, değer yansıtılmaz', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: {
        status: 422,
        body: {
          type: 'urn:netkar:problem:validation-error',
          status: 422,
          errors: [
            { field: 'valid_from', code: 'too_many_tariff_versions' },
            { field: 'brackets.0.price', code: 'price_out_of_range' },
          ],
        },
      },
    });
    const form = await fillFirstTariff(user);
    await user.click(screen.getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    await waitFor(() =>
      expect(
        within(form).getByText('Bu hesapta en çok 200 tarife sürümü tutulabilir.'),
      ).toBeInTheDocument(),
    );
    expect(
      within(form).getByText('Fiyat 0 ile 100.000 arasında ve en çok 2 ondalıklı olmalı.'),
    ).toBeInTheDocument();
    const priceInput = within(form).getByLabelText(/1\. kademe fiyatı/);
    expect(priceInput).toHaveAttribute('aria-invalid', 'true');
    // Form açık kalır, yenileme gerekmez
    expect(screen.getByRole('form', { name: 'Yeni kargo tarifesi' })).toBeInTheDocument();
  });

  it('istemci doğrulaması: boş firma ve azalan desi sunucuya gitmeden alan yanında gösterilir', async () => {
    const { api, user } = await renderPanel();
    await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
    await user.type(within(form).getByLabelText('1. kademe, en çok desi'), '5');
    await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '10');
    await user.click(within(form).getByRole('button', { name: 'Kademe ekle' }));
    await user.type(within(form).getByLabelText('2. kademe, en çok desi'), '3');
    await user.type(within(form).getByLabelText(/2\. kademe fiyatı/), '12');
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    expect(await within(form).findByText('Kargo firmasını seçin.')).toBeInTheDocument();
    expect(
      within(form).getByText('Üst desi bir önceki kademeden büyük olmalı.'),
    ).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
    // Kademe silinebilir; en az bir kademe kalır
    await user.click(within(form).getByRole('button', { name: '2. kademeyi sil' }));
    expect(within(form).queryByLabelText('2. kademe, en çok desi')).not.toBeInTheDocument();
    expect(within(form).getByRole('button', { name: '1. kademeyi sil' })).toBeDisabled();
  });

  it('firma listesi alınamazsa yalnız "Diğer firmalar" seçilebilir ve tekrar yükle çalışır', async () => {
    let fail = true;
    const { api, user } = await renderPanel({
      [`GET ${BASE}/carriers`]: () =>
        fail ? { status: 503, body: problemBody('busy') } : { body: makeCarriers() },
    });
    await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
    await within(form).findByText(/Firma listesi alınamadı/);
    const select = within(form).getByLabelText('Kargo firması');
    expect(within(select).getAllByRole('option')).toHaveLength(2);
    fail = false;
    await user.click(within(form).getByRole('button', { name: 'Listeyi tekrar yükle' }));
    await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(2));
    expect(api.count('GET', `${BASE}/carriers`)).toBe(2);
  });

  it('düzenleme: anahtar alanlar sabit, aynı anahtarla PUT; 409 sonrası onay', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        if (attempt === 1) {
          return {
            status: 409,
            body: problemBody('settings-past-change-unconfirmed', {
              affects_from: '2026-10-01',
              affects_past: true,
              current_revision: 7,
            }),
          };
        }
        return {
          body: {
            ...makeWriteInfo({ revision: 8, action: 'replaced' }),
            created: false,
            tariff: makeTariff(),
          },
        };
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    expect(within(form).queryByLabelText('Kargo firması')).not.toBeInTheDocument();
    expect(within(form).getByLabelText('1. kademe, en çok desi')).toHaveValue(
      '2.00'.replace('.', ','),
    );
    const price = within(form).getByLabelText(/1\. kademe fiyatı/);
    await user.clear(price);
    await user.type(price, '60');
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText(/Tarife güncellendi/)).toBeInTheDocument();
    expect(api.writes()[1]?.body).toMatchObject({
      carrier: 'Trendyol Express',
      valid_from: '2026-10-01',
      confirm_affects_from: '2026-10-01',
      expected_revision: 7,
      brackets: [
        { max_desi: '2.00', price: '60.00' },
        { max_desi: '5.00', price: '72.00' },
      ],
    });
  });

  it('settings-record-ended: ekran yenilenir ve satır içi role="alert" mesajı çıkar', async () => {
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: {
        status: 409,
        body: problemBody('settings-record-ended', { current_id: null }),
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const alert = await screen.findByText(
      'Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik.',
    );
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    expect(api.count('GET', BASE)).toBe(2);
    expect(
      screen.queryByRole('form', { name: 'Kargo tarifesini düzenle' }),
    ).not.toBeInTheDocument();
  });

  it('settings-revision-conflict: ekran yenilenir; düzenleme formu eski değerlerle açık kalmaz (AF-11)', async () => {
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: {
        status: 409,
        body: problemBody('settings-revision-conflict', { current_revision: 12 }),
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const alert = await screen.findByText(
      /Ayarlar siz düzenlerken başka biri tarafından değiştirildi/,
    );
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    expect(api.count('GET', BASE)).toBe(2);
    expect(
      screen.queryByRole('form', { name: 'Kargo tarifesini düzenle' }),
    ).not.toBeInTheDocument();
  });

  it('aynı içerik: değişiklik yok bilgisi', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: {
        body: {
          ...makeWriteInfo({ changed: false, action: 'unchanged', revision: 7 }),
          created: false,
          tariff: makeTariff(),
        },
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const note = await screen.findByText(/Değişiklik yok/);
    expect(note.closest('[role="status"]')).not.toBeNull();
  });

  it('geri çekme: DELETE sorgusu, 409 onayı (geri çekme metni), onayla', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`DELETE ${BASE}/cargo-tariffs/${TARIFF_ID}`]: () => {
        attempt += 1;
        if (attempt === 1) {
          return {
            status: 409,
            body: problemBody('settings-past-change-unconfirmed', {
              affects_from: '2026-10-01',
              affects_past: true,
              current_revision: 7,
            }),
          };
        }
        return {
          body: makeWriteInfo({ revision: 8, action: 'retracted', affects_from: '2026-10-01' }),
        };
      },
    });
    await user.click(screen.getByRole('button', { name: /Geri çek: Trendyol Express/ }));
    // Önce istemci onayı (WCAG 3.3.4); henüz istek yok
    const clientDialog = await screen.findByRole('alertdialog', {
      name: 'Trendyol Express tarifesi (1 Ekim 2026 başlangıçlı) geri çekilsin mi?',
    });
    expect(api.writes()).toHaveLength(0);
    await user.click(within(clientDialog).getByRole('button', { name: 'Geri çek' }));
    // Sunucu 409 verince aynı pencere ADR metnine geçer
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(dialog).toHaveTextContent(
      "Bu sürüm geri çekilirse 1 Ekim 2026 sonrası siparişlerde kargo önceki sürümden ya da 'diğer firmalar' tarifesinden hesaplanır; hiçbiri yoksa kargo 'eksik' görünür ve net kâr hesaplanamaz.",
    );
    // Geri çekmede "yalnız bugünden itibaren" düğmesi yok
    expect(
      within(dialog).queryByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).not.toBeInTheDocument();
    expect(api.writes()[0]?.query.get('expected_revision')).toBe('7');
    expect(api.writes()[0]?.query.has('confirm_affects_from')).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText(/Trendyol Express tarifesi geri çekildi/)).toBeInTheDocument();
    const second = api.writes()[1] as RecordedCall;
    expect(second.query.get('confirm_affects_from')).toBe('2026-10-01');
    expect(second.query.get('expected_revision')).toBe('7');
  });
});

describe('Hizmet bedeli tahmini', () => {
  it('0 yazılınca "0 girildi" uyarısı, KDV dahil girişte hariç karşılığı', async () => {
    const { user } = await renderPanel({}, makeEmptySettings());
    await user.click(screen.getByRole('button', { name: 'Tahmin ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni hizmet bedeli tahmini' });
    const amount = within(form).getByLabelText(/Sipariş başına tutar/);
    await user.type(amount, '12');
    expect(
      within(form).getByText('Kaydedilecek: 12,00 TL KDV dahil = 10,00 TL KDV hariç'),
    ).toBeInTheDocument();
    await user.clear(amount);
    await user.type(amount, '0');
    expect(within(form).getByText('0 girildi')).toBeInTheDocument();
  });

  it('ekleme: gövde ve onaysız ilk giriş; 0 tutar geçerlidir', async () => {
    const { api, user } = await renderPanel(
      {
        [`PUT ${BASE}/service-fee-estimates`]: {
          body: {
            ...makeWriteInfo({ revision: 1 }),
            created: true,
            estimate: makeFee({ amount: '0.00', amount_excl_vat: '0.00' }),
          },
        },
      },
      makeEmptySettings(),
    );
    await user.click(screen.getByRole('button', { name: 'Tahmin ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni hizmet bedeli tahmini' });
    await user.type(within(form).getByLabelText(/Sipariş başına tutar/), '0');
    await user.click(within(form).getByRole('radio', { name: /^KDV hariç/ }));
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    expect(await screen.findByText(/Hizmet bedeli tahmini eklendi/)).toBeInTheDocument();
    expect(api.writes()[0]?.body).toMatchObject({
      amount: '0.00',
      amount_includes_vat: false,
      expected_revision: 0,
    });
    expect(api.writes()[0]?.body).not.toHaveProperty('confirm_affects_from');
  });

  it('geri çekme sunucuya silme sorgusuyla gider', async () => {
    const { api, user } = await renderPanel({
      [`DELETE ${BASE}/service-fee-estimates/${FEE_ID}`]: {
        body: makeWriteInfo({ revision: 8, action: 'retracted' }),
      },
    });
    await user.click(
      screen.getByRole('button', { name: /Geri çek: 1 Ekim 2026 başlangıçlı tahmin/ }),
    );
    expect(api.writes()).toHaveLength(0);
    const confirmDialog = await screen.findByRole('alertdialog', {
      name: '1 Ekim 2026 başlangıçlı hizmet bedeli tahmini geri çekilsin mi?',
    });
    await user.click(within(confirmDialog).getByRole('button', { name: 'Geri çek' }));
    expect(await screen.findByText('Hizmet bedeli sürümü geri çekildi.')).toBeInTheDocument();
    expect(api.writes()[0]?.method).toBe('DELETE');
  });
});

describe('Varsayılan desi', () => {
  it('ilk giriş onaysız gönderilir', async () => {
    const { api, user } = await renderPanel(
      {
        [`PUT ${BASE}/defaults`]: {
          body: { ...makeWriteInfo({ revision: 1 }), default_desi: '2.50' },
        },
      },
      makeEmptySettings(),
    );
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    await user.type(within(form).getByLabelText('Varsayılan desi'), '2,5');
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    expect(await screen.findByText('Varsayılan desi kaydedildi.')).toBeInTheDocument();
    expect(api.writes()[0]?.body).toEqual({ default_desi: '2.5', expected_revision: 0 });
  });

  it('değiştirme tarihsiz 409 alır; onay "all" ile gönderilir ve desi metni gösterilir', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/defaults`]: () => {
        attempt += 1;
        if (attempt === 1) {
          return {
            status: 409,
            body: problemBody('settings-past-change-unconfirmed', {
              affects_from: null,
              affects_past: true,
              current_revision: 7,
            }),
          };
        }
        return {
          body: { ...makeWriteInfo({ revision: 8, action: 'replaced' }), default_desi: '4.00' },
        };
      },
    });
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    const input = within(form).getByLabelText('Varsayılan desi');
    expect(input).toHaveValue('3,00');
    await user.clear(input);
    await user.type(input, '4');
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(dialog).toHaveTextContent(
      'Siparişinde desi bilgisi olmayan tüm geçmiş siparişlerin kargo tahmini değişir.',
    );
    // Varsayılan desi için "yalnız bugünden itibaren" yoktur
    expect(
      within(dialog).queryByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText('Varsayılan desi kaydedildi.')).toBeInTheDocument();
    expect(api.writes()[1]?.body).toEqual({
      default_desi: '4',
      expected_revision: 7,
      confirm_affects_from: 'all',
    });
  });

  it('boş bırakıp kaydetmek varsayılan desiyi kaldırır (null)', async () => {
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/defaults`]: {
        body: { ...makeWriteInfo({ action: 'retracted' }), default_desi: null },
      },
    });
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    await user.clear(within(form).getByLabelText('Varsayılan desi'));
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    expect(await screen.findByText('Varsayılan desi kaldırıldı.')).toBeInTheDocument();
    expect(api.writes()[0]?.body).toMatchObject({ default_desi: null });
  });

  it('geçersiz desi sunucuya gitmeden reddedilir', async () => {
    const { api, user } = await renderPanel();
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    const input = within(form).getByLabelText('Varsayılan desi');
    await user.clear(input);
    await user.type(input, '0');
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    expect(
      await within(form).findByText("Desi 0'dan büyük, en çok 1.000 olmalı."),
    ).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });
});

describe('Değişken giderler', () => {
  it('ekleme: tutar tipi POST gövdesi; 409 onayında ikincil düğme bugünden başlatır', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`POST ${BASE}/variable-expenses`]: () => {
        attempt += 1;
        if (attempt === 1) {
          return {
            status: 409,
            body: problemBody('settings-past-change-unconfirmed', {
              affects_from: '2026-08-10',
              affects_past: true,
              current_revision: 7,
            }),
          };
        }
        return { status: 201, body: { ...makeWriteInfo({ revision: 8 }), expense: makeExpense() } };
      },
    });
    await user.click(screen.getByRole('button', { name: 'Gider ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni değişken gider' });
    await user.type(within(form).getByLabelText('Gider adı'), 'E-fatura');
    await user.type(within(form).getByLabelText(/Tutar \(KDV hariç/), '1,5');
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(
      within(dialog).getByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    );
    expect(await screen.findByText('Gider eklendi.')).toBeInTheDocument();
    expect(api.writes()[0]?.body).toMatchObject({
      name: 'E-fatura',
      kind: 'siparis_basi',
      amount_excl_vat: '1.50',
      percent: null,
      vat_rate: 20,
      valid_to: null,
    });
    expect(api.writes()[1]?.body).toMatchObject({ valid_from: TODAY, expected_revision: 7 });
    expect(api.writes()[1]?.body).not.toHaveProperty('confirm_affects_from');
  });

  it('yüzde tipinde oran alanı çıkar, tutar gönderilmez', async () => {
    const { api, user } = await renderPanel(
      {
        [`POST ${BASE}/variable-expenses`]: {
          status: 201,
          body: { ...makeWriteInfo(), expense: makeExpense() },
        },
      },
      makeEmptySettings(),
    );
    await user.click(screen.getByRole('button', { name: 'Gider ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni değişken gider' });
    await user.type(within(form).getByLabelText('Gider adı'), 'Komisyon dışı');
    await user.selectOptions(within(form).getByLabelText('Nasıl hesaplanır?'), 'satis_yuzdesi');
    expect(within(form).queryByLabelText(/Tutar \(KDV hariç/)).not.toBeInTheDocument();
    await user.type(within(form).getByLabelText(/Oran/), '2,5');
    await user.selectOptions(within(form).getByLabelText('KDV oranı'), '10');
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    expect(await screen.findByText('Gider eklendi.')).toBeInTheDocument();
    expect(api.writes()[0]?.body).toMatchObject({
      kind: 'satis_yuzdesi',
      amount_excl_vat: null,
      percent: '2.5',
      vat_rate: 10,
    });
  });

  it('düzenleme PUT /{id}; kapanmış kayıt 409 ile yenileme mesajı verir', async () => {
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/variable-expenses/${EXPENSE_ID}`]: {
        status: 409,
        body: problemBody('settings-record-ended', {
          current_id: '55555555-5555-4555-8555-555555555555',
        }),
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Paketleme/ }));
    const form = await screen.findByRole('form', { name: 'Değişken gideri düzenle' });
    const amount = within(form).getByLabelText(/Tutar \(KDV hariç/);
    expect(amount).toHaveValue('6,50');
    await user.clear(amount);
    await user.type(amount, '7');
    await user.click(within(form).getByRole('button', { name: 'Kaydet ve rakamları güncelle' }));
    expect(
      await screen.findByText('Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik.'),
    ).toBeInTheDocument();
    expect(api.writes()[0]?.path).toBe(`${BASE}/variable-expenses/${EXPENSE_ID}`);
    expect(api.count('GET', BASE)).toBe(2);
  });

  it('geri çekme: DELETE', async () => {
    const { api, user } = await renderPanel({
      [`DELETE ${BASE}/variable-expenses/${EXPENSE_ID}`]: {
        body: makeWriteInfo({ action: 'retracted' }),
      },
    });
    await user.click(screen.getByRole('button', { name: /Geri çek: Paketleme/ }));
    expect(api.writes()).toHaveLength(0);
    const confirmDialog = await screen.findByRole('alertdialog', {
      name: 'Paketleme gideri geri çekilsin mi?',
    });
    await user.click(within(confirmDialog).getByRole('button', { name: 'Geri çek' }));
    expect(await screen.findByText('Paketleme gideri geri çekildi.')).toBeInTheDocument();
    expect(api.writes()[0]?.method).toBe('DELETE');
  });
});

describe('Ayar geçmişi', () => {
  it('kayıtları cümle ve fark olarak, rozetlerle gösterir', async () => {
    await renderPanel({
      [`GET ${BASE}/history`]: {
        body: makeHistory([
          makeHistoryItem(),
          makeHistoryItem({
            revision: 6,
            action: 'geri_cek',
            past_change_confirmed: false,
            affects_past: false,
            replaced_record: null,
          }),
        ]),
      },
    });
    const list = await screen.findByRole('list', { name: 'Ayar değişiklikleri' });
    const items = Array.from(list.children);
    expect(items[0]).toHaveTextContent('10 Kasım 2026, 14:35, Yönetici');
    expect(items[0]).toHaveTextContent(
      'Trendyol Express tarifesi (başlangıç 1 Ekim 2026) değiştirildi',
    );
    expect(items[0]).toHaveTextContent('2 desi 54,00 → 60,00 (KDV dahil)');
    expect(items[0]).toHaveTextContent('Geçmişi etkiledi (onaylı)');
    expect(items[1]).toHaveTextContent('Geri çekildi');
    expect(items[1]).not.toHaveTextContent('Geçmişi etkiledi');
  });

  it('boş geçmiş boş durum metni verir', async () => {
    await renderPanel({ [`GET ${BASE}/history`]: { body: makeHistory([]) } });
    expect(await screen.findByText(/Henüz ayar değişikliği yok/)).toBeInTheDocument();
  });

  it('hata durumunda tekrar dene sunar', async () => {
    let fail = true;
    const { api, user } = await renderPanel({
      [`GET ${BASE}/history`]: () =>
        fail ? { status: 500, body: problemBody('boom') } : { body: makeHistory() },
    });
    const alert = await screen.findByText('Ayar geçmişi yüklenemedi');
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    fail = false;
    const retry = within(alert.closest('[role="alert"]') as HTMLElement).getByRole('button', {
      name: 'Tekrar dene',
    });
    await user.click(retry);
    expect(await screen.findByRole('list', { name: 'Ayar değişiklikleri' })).toBeInTheDocument();
    expect(api.count('GET', `${BASE}/history`)).toBe(2);
  });

  it('daha fazla göster imleci gönderir; imleç geçersizse baştan yükler', async () => {
    let served = 0;
    const { api, user } = await renderPanel({
      [`GET ${BASE}/history`]: (call) => {
        if (call.query.get('cursor') === 'eski') {
          return {
            status: 422,
            body: {
              type: 'urn:netkar:problem:validation-error',
              status: 422,
              errors: [{ field: 'cursor', code: 'cursor_invalid' }],
            },
          };
        }
        served += 1;
        return {
          body: makeHistory([makeHistoryItem({ revision: 100 + served })], {
            next_cursor: served === 1 ? 'eski' : null,
          }),
        };
      },
    });
    await screen.findByRole('list', { name: 'Ayar değişiklikleri' });
    expect(api.calls.find((c) => c.path === `${BASE}/history`)?.query.get('limit')).toBe('20');
    await user.click(screen.getByRole('button', { name: 'Daha fazla göster' }));
    await waitFor(() =>
      expect(screen.getByText('Liste güncellendiği için baştan yüklendi.')).toBeInTheDocument(),
    );
  });
});

describe('Kurulum özeti', () => {
  it('derin bağlantı hedefleri sayfada bulunur', async () => {
    await renderPanel();
    for (const id of ['kargo', 'hizmet-bedeli', 'desi', 'giderler', 'gecmis']) {
      expect(document.getElementById(id)).not.toBeNull();
    }
    const nav = screen.getByRole('navigation', { name: 'Ayar bölümleri' });
    expect(within(nav).getByRole('link', { name: 'Kargo tarifesi' })).toHaveAttribute(
      'href',
      '#kargo',
    );
    expect(within(nav).getByRole('link', { name: 'Hizmet bedeli' })).toHaveAttribute(
      'href',
      '#hizmet-bedeli',
    );
  });
});
