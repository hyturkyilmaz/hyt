import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NotificationSettings } from '@/components/notifications/notification-settings';
import { makeAlertSettings, makePreferences } from '@/lib/alerts/test-fixtures';
import { ACCOUNT_ID, makeAccounts } from '@/lib/profit/test-fixtures';
import { mockRequests, problemReply, type Route } from '@/test/request-mock';

const base = `/api/v1/marketplace-accounts/${ACCOUNT_ID}`;
const SETTINGS = `${base}/alert-settings`;
const PREFS = '/api/v1/me/notification-preferences';

const accounts: Route = (r) =>
  r.url.pathname === '/api/v1/marketplace-accounts' ? { body: makeAccounts() } : undefined;
const me =
  (role: string, verified = true): Route =>
  (r) =>
    r.url.pathname === '/api/v1/me'
      ? { body: { role, email: 'ad@ornek.com', email_verified: verified } }
      : undefined;
const csrf: Route = (r) =>
  r.url.pathname === '/api/v1/auth/csrf' ? { body: { csrf_token: 'test-csrf' } } : undefined;
const prefsGet: Route = (r) =>
  r.method === 'GET' && r.url.pathname === PREFS ? { body: makePreferences() } : undefined;
const settingsGet =
  (etag: string, over = {}): Route =>
  (r) =>
    r.method === 'GET' && r.url.pathname === SETTINGS
      ? { body: makeAlertSettings(over), headers: { ETag: etag } }
      : undefined;

beforeEach(() => {
  document.cookie = '__Host-nk_csrf=test-csrf; path=/';
});
afterEach(() => {
  vi.unstubAllGlobals();
});

async function openThresholds() {
  return screen.findByRole('form', { name: 'Hesap eşikleri' });
}

describe('Ayarlar > Bildirimler: kullanıcı tercihleri', () => {
  it('4 kural için e-posta seçicisi ve devre dışı push seçicisi (Yakında) gösterir', async () => {
    mockRequests(accounts, me('owner'), prefsGet, settingsGet('"e-1"'));
    render(<NotificationSettings />);
    const form = await screen.findByRole('form', { name: 'Bildirim tercihleri' });
    const emailSelects = within(form).getAllByRole('combobox', { name: /E-posta$/ });
    expect(emailSelects).toHaveLength(4);
    expect(emailSelects[0]).toHaveValue('digest');
    expect(within(form).getByRole('combobox', { name: 'Zararına satış E-posta' })).toBeEnabled();
    const push = within(form).getByRole('combobox', { name: /Zararına satış Anlık bildirim/ });
    expect(push).toBeDisabled();
    expect(within(form).getAllByText('Yakında').length).toBeGreaterThanOrEqual(5);
    expect(within(form).getByLabelText('Sessiz saatler: başlangıç')).toHaveValue('22:00');
    expect(within(form).getByLabelText('Sessiz saatler: bitiş')).toHaveValue('08:00');
    expect(within(form).getByLabelText('Günlük özet saati')).toHaveValue('8');
    expect(within(form).getByLabelText('E-postada tutar göster')).toBeChecked();
  });

  it('kaydet: değişen alanlar ve değişmeyen push değerleri tam gövdeyle PUT edilir', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      prefsGet,
      settingsGet('"e-1"'),
      (r) => (r.method === 'PUT' && r.url.pathname === PREFS ? { body: r.body } : undefined),
    );
    render(<NotificationSettings />);
    const form = await screen.findByRole('form', { name: 'Bildirim tercihleri' });
    await userEvent.selectOptions(
      within(form).getByRole('combobox', { name: 'Reklam kârı yiyor E-posta' }),
      'instant',
    );
    await userEvent.selectOptions(within(form).getByLabelText('Günlük özet saati'), '9');
    await userEvent.click(within(form).getByLabelText('E-postada tutar göster'));
    await userEvent.click(within(form).getByRole('button', { name: 'Tercihleri kaydet' }));
    expect(await screen.findByText('Bildirim tercihleriniz kaydedildi.')).toBeVisible();
    const put = requests.find((r) => r.method === 'PUT');
    expect(put?.body).toEqual({
      ...makePreferences(),
      matrix: {
        ...makePreferences().matrix,
        REKLAM_KARI_YIYOR: { email: 'instant', push: 'off' },
      },
      digest_hour: 9,
      show_amounts_email: false,
    });
  });

  it('geçersiz sessiz saat istek göndermez ve alanın yanında hata gösterir', async () => {
    const { requests } = mockRequests(accounts, me('owner'), csrf, prefsGet, settingsGet('"e-1"'));
    render(<NotificationSettings />);
    const form = await screen.findByRole('form', { name: 'Bildirim tercihleri' });
    const start = within(form).getByLabelText('Sessiz saatler: başlangıç');
    // type="time" jsdom'da geçersiz değeri temizler; boş değer de geçersizdir
    await userEvent.clear(start);
    await userEvent.click(within(form).getByRole('button', { name: 'Tercihleri kaydet' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('SS:DD biçiminde');
    expect(start).toHaveAttribute('aria-invalid', 'true');
    expect(requests.some((r) => r.method === 'PUT')).toBe(false);
  });

  it('viewer kendi tercihini kaydedebilir (tercihler kişiseldir)', async () => {
    mockRequests(accounts, me('viewer'), csrf, prefsGet, settingsGet('"e-1"'), (r) =>
      r.method === 'PUT' && r.url.pathname === PREFS ? { body: r.body } : undefined,
    );
    render(<NotificationSettings />);
    const form = await screen.findByRole('form', { name: 'Bildirim tercihleri' });
    await userEvent.click(within(form).getByRole('button', { name: 'Tercihleri kaydet' }));
    expect(await screen.findByText('Bildirim tercihleriniz kaydedildi.')).toBeVisible();
  });

  it('429: bekleme süresi gösterilir', async () => {
    mockRequests(accounts, me('owner'), csrf, prefsGet, settingsGet('"e-1"'), (r) =>
      r.method === 'PUT' ? problemReply(429, 'rate-limited', { 'Retry-After': '3000' }) : undefined,
    );
    render(<NotificationSettings />);
    const form = await screen.findByRole('form', { name: 'Bildirim tercihleri' });
    await userEvent.click(within(form).getByRole('button', { name: 'Tercihleri kaydet' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Çok fazla deneme yaptınız. Yaklaşık 50 dakika sonra tekrar deneyin.',
    );
  });
});

describe('Ayarlar > Bildirimler: hesap eşikleri', () => {
  it("GET ETag'i PUT'ta If-Match olarak gönderilir; gövde Decimal dizgeleridir", async () => {
    const { requests } = mockRequests(
      accounts,
      me('admin'),
      csrf,
      prefsGet,
      settingsGet('"e-1"'),
      (r) =>
        r.method === 'PUT' && r.url.pathname === SETTINGS
          ? {
              body: makeAlertSettings({ loss_min_amount: '12.50' }),
              headers: { ETag: '"e-2"' },
            }
          : undefined,
    );
    render(<NotificationSettings />);
    const form = await openThresholds();
    const loss = within(form).getByLabelText(/Zarar bildirimi alt sınırı/);
    expect(loss).toHaveValue('5,00');
    await userEvent.clear(loss);
    await userEvent.type(loss, '12,5');
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));
    expect(await screen.findByText(/Eşikler kaydedildi/)).toBeVisible();
    const put = requests.find((r) => r.method === 'PUT' && r.url.pathname === SETTINGS);
    expect(put?.headers.get('If-Match')).toBe('"e-1"');
    expect(put?.body).toEqual({
      loss_min_amount: '12.50',
      ad_share_percent: '100.00',
      ad_min_spend: '50.00',
      deduction_notify_min: '10.00',
      return_min_diff_points: '5.00',
      rules_enabled: [
        'ZARARINA_SATIS',
        'REKLAM_KARI_YIYOR',
        'BEKLENMEYEN_KESINTI',
        'IADE_ORANI_ARTISI',
      ],
    });

    // Sonraki kayıt PUT yanıtındaki yeni ETag'i kullanır (GET'e dönmeden)
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));
    await waitFor(() =>
      expect(
        requests.filter((r) => r.method === 'PUT' && r.url.pathname === SETTINGS),
      ).toHaveLength(2),
    );
    expect(
      requests
        .filter((r) => r.method === 'PUT' && r.url.pathname === SETTINGS)[1]
        ?.headers.get('If-Match'),
    ).toBe('"e-2"');
  });

  it.each([
    ['Reklam payı eşiği', '49', /%50 ile %100 arasında/],
    ['Reklam payı eşiği', '101', /%50 ile %100 arasında/],
    ['Zarar bildirimi alt sınırı', '1.000.001', /0 ile 1\.000\.000 TL/],
    ['Zarar bildirimi alt sınırı', '12.5', /virgül/],
    ['Kesinti bildirimi alt sınırı', '1,234', /Kuruş en fazla 2 hane/],
    ['İade oranı en az fark', '100,5', /0 ile 100 puan/],
    ['Reklam en az harcama', '', /yazın/],
  ])('%s alanında "%s" değeri reddedilir, istek gitmez', async (label, value, message) => {
    const { requests } = mockRequests(accounts, me('owner'), csrf, prefsGet, settingsGet('"e-1"'));
    render(<NotificationSettings />);
    const form = await openThresholds();
    const field = within(form).getByLabelText(label, { exact: false });
    await userEvent.clear(field);
    if (value) await userEvent.type(field, value);
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));
    expect(await within(form).findByText(message)).toBeVisible();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(requests.some((r) => r.method === 'PUT' && r.url.pathname === SETTINGS)).toBe(false);
  });

  it('412: iskelete dönmez; güncel değer ve yeni ETag gelir, taslak "sizin değeriniz / güncel değer" olarak gösterilir, odak bildirimde', async () => {
    let gets = 0;
    let puts = 0;
    const { requests } = mockRequests(accounts, me('owner'), csrf, prefsGet, (r) => {
      if (r.method === 'GET' && r.url.pathname === SETTINGS) {
        gets += 1;
        return gets === 1
          ? { body: makeAlertSettings(), headers: { ETag: '"e-1"' } }
          : { body: makeAlertSettings({ loss_min_amount: '99.00' }), headers: { ETag: '"e-9"' } };
      }
      if (r.method === 'PUT' && r.url.pathname === SETTINGS) {
        puts += 1;
        return puts === 1
          ? problemReply(412, 'alert-settings-changed', { ETag: '"e-9"' })
          : { body: makeAlertSettings({ loss_min_amount: '99.00' }), headers: { ETag: '"e-10"' } };
      }
      return undefined;
    });
    render(<NotificationSettings />);
    const form = await openThresholds();
    const loss = within(form).getByLabelText(/Zarar bildirimi alt sınırı/);
    await userEvent.clear(loss);
    await userEvent.type(loss, '12,5');
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'Eşikler siz düzenlerken başka biri tarafından değiştirildi. Güncel değerler yüklendi',
    );
    await waitFor(() => expect(gets).toBe(2));
    // İskelete dönülmedi: form hiç kaybolmadı ve güncel değeri gösteriyor
    expect(screen.queryByText('Yükleniyor')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(within(form).getByLabelText(/Zarar bildirimi alt sınırı/)).toHaveValue('99,00'),
    );
    const compare = await screen.findByRole('region', {
      name: 'Sizin değerleriniz ve güncel değerler',
    });
    expect(compare).toHaveTextContent(
      'Zarar bildirimi alt sınırı: sizin değeriniz 12,50 TL, güncel değer 99,00 TL',
    );
    // Odak bildirim bölgesine taşındı
    const region = alert.closest('[tabindex="-1"]');
    await waitFor(() => expect(region).toHaveFocus());

    // İkinci kayıt güncel ETag ile gider
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));
    await waitFor(() =>
      expect(
        requests.filter((r) => r.method === 'PUT' && r.url.pathname === SETTINGS),
      ).toHaveLength(2),
    );
    const second = requests.filter((r) => r.method === 'PUT' && r.url.pathname === SETTINGS)[1];
    expect(second?.headers.get('If-Match')).toBe('"e-9"');
  });

  it('eşik kaydı sürerken ikinci tıklama ikinci PUT göndermez (ref kilidi)', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner'),
      csrf,
      prefsGet,
      settingsGet('"e-1"'),
      (r) =>
        r.method === 'PUT' && r.url.pathname === SETTINGS
          ? { body: makeAlertSettings(), headers: { ETag: '"e-2"' } }
          : undefined,
    );
    render(<NotificationSettings />);
    const form = await openThresholds();
    const button = within(form).getByRole('button', { name: 'Eşikleri kaydet' });
    button.click();
    button.click();
    await screen.findByText(/Eşikler kaydedildi/);
    expect(requests.filter((r) => r.method === 'PUT' && r.url.pathname === SETTINGS)).toHaveLength(
      1,
    );
  });

  it('429: bekleme süresi gösterilir', async () => {
    mockRequests(accounts, me('owner'), csrf, prefsGet, settingsGet('"e-1"'), (r) =>
      r.method === 'PUT' && r.url.pathname === SETTINGS
        ? problemReply(429, 'rate-limited', { 'Retry-After': '45' })
        : undefined,
    );
    render(<NotificationSettings />);
    const form = await openThresholds();
    await userEvent.click(within(form).getByRole('button', { name: 'Eşikleri kaydet' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Çok fazla deneme yaptınız. Birkaç saniye sonra tekrar deneyin.',
    );
  });

  it('viewer: form yok, değerler salt okur ve açıklayıcı not var', async () => {
    mockRequests(accounts, me('viewer'), prefsGet, settingsGet('"e-1"'));
    render(<NotificationSettings />);
    expect(await screen.findByText(/yalnız görüntüleyebilirsiniz/)).toBeVisible();
    expect(screen.queryByRole('form', { name: 'Hesap eşikleri' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Eşikleri kaydet' })).not.toBeInTheDocument();
    expect(screen.getByText('5,00 TL')).toBeVisible();
    expect(screen.getByText('%100,00')).toBeVisible();
  });

  it('doğrulanmamış e-posta: eşik kaydet aria-disabled ve istek yok; tercihler (backend istemiyor) kaydedilir', async () => {
    const { requests } = mockRequests(
      accounts,
      me('owner', false),
      csrf,
      prefsGet,
      settingsGet('"e-1"'),
      (r) => (r.method === 'PUT' && r.url.pathname === PREFS ? { body: r.body } : undefined),
    );
    render(<NotificationSettings />);
    const form = await openThresholds();
    const save = within(form).getByRole('button', { name: 'Eşikleri kaydet' });
    await waitFor(() => expect(save).toHaveAttribute('aria-disabled', 'true'));
    expect(save).not.toBeDisabled();
    expect(save.getAttribute('aria-describedby')).toBe('eposta-dogrulama-notu');
    expect(document.getElementById('eposta-dogrulama-notu')).toHaveTextContent(/eşikleri/);
    await userEvent.click(save);
    expect(requests.some((r) => r.method === 'PUT')).toBe(false);

    const prefsSave = screen.getByRole('button', { name: 'Tercihleri kaydet' });
    expect(prefsSave).not.toHaveAttribute('aria-disabled');
    await userEvent.click(prefsSave);
    expect(await screen.findByText('Bildirim tercihleriniz kaydedildi.')).toBeVisible();
  });

  it('kanallar: e-posta adresi ve doğrulama durumu gösterilir', async () => {
    mockRequests(accounts, me('owner', false), prefsGet, settingsGet('"e-1"'));
    render(<NotificationSettings />);
    const channels = await screen.findByRole('region', { name: 'Kanallar' });
    expect(await within(channels).findByText('ad@ornek.com')).toBeVisible();
    expect(within(channels).getByText('Doğrulanmadı')).toBeVisible();
    expect(within(channels).getByText('Yakında')).toBeVisible();
  });

  it('rol okunamazsa "yetki okunamadı" notu çıkar', async () => {
    mockRequests(
      accounts,
      (r) => (r.url.pathname === '/api/v1/me' ? problemReply(500, 'internal-error') : undefined),
      prefsGet,
      settingsGet('"e-1"'),
    );
    render(<NotificationSettings />);
    expect((await screen.findAllByText(/Yetkiniz okunamadı/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole('form', { name: 'Hesap eşikleri' })).not.toBeInTheDocument();
  });

  it('kayıt yoksa varsayılan değerlerin gösterildiğini söyler', async () => {
    mockRequests(
      accounts,
      me('owner'),
      prefsGet,
      settingsGet('"e-0"', { is_default: true, updated_at: null }),
    );
    render(<NotificationSettings />);
    expect(await screen.findByText(/varsayılan değerler gösteriliyor/)).toBeVisible();
  });

  it('mağaza yoksa eşikler açılmaz ama tercihler çalışır', async () => {
    mockRequests(
      (r) => (r.url.pathname === '/api/v1/marketplace-accounts' ? { body: [] } : undefined),
      me('owner'),
      prefsGet,
    );
    render(<NotificationSettings />);
    expect(await screen.findByText(/Eşikler Trendyol mağazanızı bağlayınca açılır/)).toBeVisible();
    expect(await screen.findByRole('form', { name: 'Bildirim tercihleri' })).toBeVisible();
  });
});
