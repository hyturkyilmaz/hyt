// Kâr ayarları paneli akış testleri (denetim AF-01..AF-16): odak, onay pencereleri, ikinci 409, sözleşme.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProfitSettingsPanel } from '@/components/settings/profit-settings-panel';
import { todayIstanbul } from '@/lib/profit/settings-input';
import {
  EXPENSE_ID,
  FEE_ID,
  TARIFF_ID,
  makeEmptySettings,
  makeExpense,
  makeFee,
  makeSettings,
  makeTariff,
  makeWriteInfo,
} from '@/lib/profit/settings-fixtures';
import { ACCOUNT_ID } from '@/lib/profit/test-fixtures';
import { installFakeApi, problemBody, type RecordedCall } from '@/test/settings-api-mock';
import {
  BODY_SPECS,
  DELETE_QUERY_PARAMS,
  bodyViolations,
  bracketViolations,
  contractKeyOf,
} from '@/test/profit-settings-contract';
import { BASE, renderPanel, routes } from '@/test/settings-panel-harness';

const TODAY = todayIstanbul();
const SAVE = 'Kaydet ve rakamları güncelle';
const OTHER_TARIFF_ID = '55555555-5555-4555-8555-555555555555';

afterEach(() => {
  vi.unstubAllGlobals();
});

function past409(affectsFrom: string | null, revision = 9) {
  return {
    status: 409,
    body: problemBody('settings-past-change-unconfirmed', {
      affects_from: affectsFrom,
      affects_past: true,
      current_revision: revision,
    }),
  };
}

const TARIFF_OK = {
  body: { ...makeWriteInfo({ revision: 10 }), created: true, tariff: makeTariff() },
};

async function fillNewTariff(user: ReturnType<typeof userEvent.setup>, carrier = 'Yurtiçi Kargo') {
  await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
  const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
  await user.selectOptions(within(form).getByLabelText('Kargo firması'), carrier);
  await user.type(within(form).getByLabelText('1. kademe, en çok desi'), '2');
  await user.type(within(form).getByLabelText(/1\. kademe fiyatı/), '54');
  return form;
}

describe('AF-02: onay penceresi odağı (WCAG 2.4.3)', () => {
  it('geri çekme penceresi açılışta "Vazgeç"e odaklanır; Esc odağı "Geri çek" düğmesine döndürür', async () => {
    const { api, user } = await renderPanel();
    const trigger = screen.getByRole('button', { name: /Geri çek: Trendyol Express/ });
    await user.click(trigger);
    const dialog = await screen.findByRole('alertdialog');
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Vazgeç' })).toHaveFocus(),
    );
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(api.writes()).toHaveLength(0);
  });

  it('geri çekme penceresinde Vazgeç odağı tetikleyiciye döndürür', async () => {
    const { user } = await renderPanel();
    const trigger = screen.getByRole('button', { name: /Geri çek: Trendyol Express/ });
    await user.click(trigger);
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Vazgeç' }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it('409 penceresinde Vazgeç odağı formun kaydet düğmesine döndürür', async () => {
    const { user } = await renderPanel({ [`PUT ${BASE}/cargo-tariffs`]: past409('2026-08-10') });
    const form = await fillNewTariff(user);
    const save = within(form).getByRole('button', { name: SAVE });
    await user.click(save);
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Vazgeç' })).toHaveFocus(),
    );
    await user.click(within(dialog).getByRole('button', { name: 'Vazgeç' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    await waitFor(() => expect(save).toHaveFocus());
  });

  it('pencereden başarılı uygulamada odak bölüm başlığına gider (form kapanır, tetikleyici kalkar)', async () => {
    let attempt = 0;
    const { user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        return attempt === 1 ? past409('2026-08-10') : TARIFF_OK;
      },
    });
    await fillNewTariff(user);
    await user.click(screen.getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    await screen.findByText(/Tarife eklendi/);
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2, name: 'Kargo tarifesi' })).toHaveFocus(),
    );
  });

  it('pencere açılmadan biten başarılı yazımda da odak bölüm başlığına gider', async () => {
    let saved = false;
    const { user } = await renderPanel(
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
          return TARIFF_OK;
        },
      },
      makeEmptySettings(),
    );
    await fillNewTariff(user);
    await user.click(screen.getByRole('button', { name: SAVE }));
    await screen.findByText(/Tarife eklendi/);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2, name: 'Kargo tarifesi' })).toHaveFocus(),
    );
  });

  it('pencere alertdialog rolündedir ve dışarı tıklamak onu kapatmaz', async () => {
    const { api, user } = await renderPanel();
    await user.click(screen.getByRole('button', { name: /Geri çek: Trendyol Express/ }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveAccessibleDescription('Önceki değer ayar geçmişinde kalır.');
    // Dışarıya basış (modal açıkken gövde tıklanamaz; Radix belge düzeyinde pointerdown dinler)
    fireEvent.pointerDown(document.body);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });
});

describe('AF-03: geri çekme istemci onayı (WCAG 3.3.4)', () => {
  it('geçmişi etkilemeyen (409 gelmeyen) geri çekme de önce onay ister; Vazgeç hiçbir şey göndermez', async () => {
    const { api, user } = await renderPanel({
      [`DELETE ${BASE}/cargo-tariffs/${TARIFF_ID}`]: {
        body: makeWriteInfo({ revision: 8, action: 'retracted' }),
      },
    });
    await user.click(screen.getByRole('button', { name: /Geri çek: Trendyol Express/ }));
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Trendyol Express tarifesi (1 Ekim 2026 başlangıçlı) geri çekilsin mi?',
    });
    expect(dialog).toHaveTextContent('Önceki değer ayar geçmişinde kalır.');
    await user.click(within(dialog).getByRole('button', { name: 'Vazgeç' }));
    expect(api.writes()).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: /Geri çek: Trendyol Express/ }));
    const again = await screen.findByRole('alertdialog');
    await user.click(within(again).getByRole('button', { name: 'Geri çek' }));
    expect(await screen.findByText(/Trendyol Express tarifesi geri çekildi/)).toBeInTheDocument();
    // Tek istek: onay penceresi ikinci bir pencere açmadı
    expect(api.writes()).toHaveLength(1);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('istemci onayından sonra sunucu 409 verirse aynı pencere ADR metnine geçer (iki pencere üst üste yok)', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`DELETE ${BASE}/variable-expenses/${EXPENSE_ID}`]: () => {
        attempt += 1;
        return attempt === 1
          ? past409('2026-10-01', 7)
          : { body: makeWriteInfo({ revision: 8, action: 'retracted' }) };
      },
    });
    await user.click(screen.getByRole('button', { name: /Geri çek: Paketleme/ }));
    const first = await screen.findByRole('alertdialog', {
      name: 'Paketleme gideri geri çekilsin mi?',
    });
    await user.click(within(first).getByRole('button', { name: 'Geri çek' }));
    const second = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(screen.getAllByRole('alertdialog')).toHaveLength(1);
    // Yeni metin yeni bir pencere gibi okunur: odak güvenli düğmede
    await waitFor(() =>
      expect(within(second).getByRole('button', { name: 'Vazgeç' })).toHaveFocus(),
    );
    expect(within(second).queryByText(/Etkilenen tarih değişti/)).not.toBeInTheDocument();
    await user.click(within(second).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText('Paketleme gideri geri çekildi.')).toBeInTheDocument();
    expect(api.writes()).toHaveLength(2);
    expect(api.writes()[1]?.query.get('confirm_affects_from')).toBe('2026-10-01');
  });
});

describe('AF-06: pencere içindeki ikinci 409', () => {
  it('etki tarihi değişince not çıkar; otomatik yeniden gönderim olmaz, yeni tıklama yeni tarihi gönderir', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        if (attempt === 1) return past409('2026-08-10', 9);
        if (attempt === 2) return past409('2026-08-01', 10);
        return TARIFF_OK;
      },
    });
    await fillNewTariff(user);
    await user.click(screen.getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(dialog).toHaveTextContent('10 Ağustos 2026 ve sonrasındaki');
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));

    // İkinci 409: pencere açık kalır, yeni tarih ve not görünür
    expect(await within(dialog).findByText(/Etkilenen tarih değişti/)).toBeInTheDocument();
    expect(dialog).toHaveTextContent('1 Ağustos 2026 ve sonrasındaki');
    expect(api.writes()).toHaveLength(2);
    expect(api.writes()[1]?.body).toMatchObject({
      confirm_affects_from: '2026-08-10',
      expected_revision: 9,
    });

    // Otomatik yeniden gönderim yok: bir süre beklenince istek sayısı artmaz
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(api.writes()).toHaveLength(2);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();

    // Kullanıcı yeni metni okuyup yeniden onaylayınca yeni tarih ve yeni sürüm gider
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    expect(await screen.findByText(/Tarife eklendi/)).toBeInTheDocument();
    expect(api.writes()).toHaveLength(3);
    expect(api.writes()[2]?.body).toMatchObject({
      confirm_affects_from: '2026-08-01',
      expected_revision: 10,
    });
  });

  it('etki tarihi aynı kalan ikinci 409 not göstermez ama yine otomatik gönderilmez', async () => {
    let attempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        attempt += 1;
        return attempt <= 2 ? past409('2026-08-10', 9 + attempt) : TARIFF_OK;
      },
    });
    await fillNewTariff(user);
    await user.click(screen.getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    await waitFor(() => expect(api.writes()).toHaveLength(2));
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Değişikliği uygula' })).toBeEnabled(),
    );
    expect(within(dialog).queryByText(/Etkilenen tarih değişti/)).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(api.writes()).toHaveLength(2);
  });
});

describe('AF-07: "Yalnız bugünden itibaren uygula" kapsamı (ADR-0007 §5.2)', () => {
  it('düzenlemede yoktur: eski sürümü düzeltmek isteyen yanlışlıkla yeni sürüm eklemez', async () => {
    const { user } = await renderPanel({ [`PUT ${BASE}/cargo-tariffs`]: past409('2026-10-01', 7) });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    await user.click(within(form).getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(
      within(dialog).queryByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).not.toBeInTheDocument();
  });

  it('hizmet bedeli düzenlemesinde de yoktur', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/service-fee-estimates`]: past409('2026-10-01', 7),
    });
    await user.click(
      screen.getByRole('button', { name: /Düzenle: 1 Ekim 2026 başlangıçlı tahmin/ }),
    );
    const form = await screen.findByRole('form', { name: 'Hizmet bedeli tahminini düzenle' });
    await user.click(within(form).getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(
      within(dialog).queryByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).not.toBeInTheDocument();
  });

  it('aynı anahtarlı bugünkü sürüm varsa eklemede de yoktur (sessizce ezmesin)', async () => {
    const { user } = await renderPanel(
      { [`PUT ${BASE}/cargo-tariffs`]: past409('2026-08-10') },
      makeSettings({
        cargo_tariffs: [makeTariff(), makeTariff({ id: OTHER_TARIFF_ID, valid_from: TODAY })],
      }),
    );
    await fillNewTariff(user, 'Trendyol Express');
    await user.click(screen.getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(
      within(dialog).queryByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).not.toBeInTheDocument();
  });

  it('başka firmanın bugünkü sürümü ikincil düğmeyi engellemez', async () => {
    const { user } = await renderPanel(
      { [`PUT ${BASE}/cargo-tariffs`]: past409('2026-08-10') },
      makeSettings({
        cargo_tariffs: [makeTariff(), makeTariff({ id: OTHER_TARIFF_ID, valid_from: TODAY })],
      }),
    );
    await fillNewTariff(user, 'Yurtiçi Kargo');
    await user.click(screen.getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    expect(
      within(dialog).getByRole('button', { name: 'Yalnız bugünden itibaren uygula' }),
    ).toBeInTheDocument();
  });
});

describe('AF-16: etki tarihi olmayan 409', () => {
  it('tarihli yazımda pencere açılmaz, hata bildirimi çıkar ve hiçbir şey kaydedilmez', async () => {
    const { api, user } = await renderPanel({ [`PUT ${BASE}/cargo-tariffs`]: past409(null) });
    await fillNewTariff(user);
    await user.click(screen.getByRole('button', { name: SAVE }));
    const alert = await screen.findByText(/Değişikliğin etkileyeceği tarih alınamadı/);
    expect(alert.closest('[role="alert"]')).not.toBeNull();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(api.writes()).toHaveLength(1);
  });
});

describe('AF-01: tr-TR sayı girişi (tek kural, yansıma)', () => {
  it('"12,550" para alanında binlik sayılmaz: kuruş hatası, istek gitmez', async () => {
    const { api, user } = await renderPanel();
    const form = await fillNewTariff(user);
    const price = within(form).getByLabelText(/1\. kademe fiyatı/);
    await user.clear(price);
    await user.type(price, '12,550');
    expect(within(form).getByText(/Okunamadı: kuruş en fazla 2 hane/)).toBeInTheDocument();
    await user.click(within(form).getByRole('button', { name: SAVE }));
    expect(await within(form).findByText(/Kuruş en fazla 2 hane olabilir/)).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });

  it('"12.5" belirsizdir: canlı uyarı ve gönderimde hata', async () => {
    const { api, user } = await renderPanel();
    const form = await fillNewTariff(user);
    const price = within(form).getByLabelText(/1\. kademe fiyatı/);
    await user.clear(price);
    await user.type(price, '12.5');
    expect(within(form).getByText(/Okunamadı: ondalık için virgül yazın/)).toBeInTheDocument();
    await user.click(within(form).getByRole('button', { name: SAVE }));
    expect(await within(form).findByText(/virgül kullanın \(örnek:/)).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });

  it('doğru gruplanmış "1.250,00" yansıtılır; KDV hariç girişte de yansıma vardır', async () => {
    const { user } = await renderPanel();
    const form = await fillNewTariff(user);
    const price = within(form).getByLabelText(/1\. kademe fiyatı/);
    await user.clear(price);
    await user.type(price, '1.250,00');
    expect(
      within(form).getByText('Kaydedilecek: 1.250,00 TL KDV dahil = 1.041,67 TL KDV hariç'),
    ).toBeInTheDocument();
    await user.click(within(form).getByRole('radio', { name: /^KDV hariç/ }));
    expect(within(form).getByText('Kaydedilecek: 1.250,00 TL KDV hariç')).toBeInTheDocument();
  });

  it('desi alanı da ayrıştırılan değeri yansıtır', async () => {
    const { user } = await renderPanel();
    const form = await fillNewTariff(user);
    const desi = within(form).getByLabelText('1. kademe, en çok desi');
    await user.clear(desi);
    await user.type(desi, '2,5');
    expect(within(form).getByText('Kaydedilecek: 2,5 desi')).toBeInTheDocument();
  });

  it('hizmet bedeli (hariç mod) ve gider tutarı ayrıştırılan değeri yansıtır', async () => {
    const { user } = await renderPanel({}, makeEmptySettings());
    await user.click(screen.getByRole('button', { name: 'Tahmin ekle' }));
    const fee = await screen.findByRole('form', { name: 'Yeni hizmet bedeli tahmini' });
    await user.type(within(fee).getByLabelText(/Sipariş başına tutar/), '12,55');
    await user.click(within(fee).getByRole('radio', { name: /^KDV hariç/ }));
    expect(within(fee).getByText('Kaydedilecek: 12,55 TL KDV hariç')).toBeInTheDocument();
    await user.click(within(fee).getByRole('button', { name: 'Vazgeç' }));

    await user.click(screen.getByRole('button', { name: 'Gider ekle' }));
    const expense = await screen.findByRole('form', { name: 'Yeni değişken gider' });
    await user.type(within(expense).getByLabelText(/Tutar \(KDV hariç/), '1.250');
    expect(within(expense).getByText('Kaydedilecek: 1.250,00 TL KDV hariç')).toBeInTheDocument();
    await user.selectOptions(within(expense).getByLabelText('Nasıl hesaplanır?'), 'satis_yuzdesi');
    await user.type(within(expense).getByLabelText(/Oran/), '2,5');
    expect(within(expense).getByText('Kaydedilecek: %2,5')).toBeInTheDocument();
  });

  it('oran alanı para alanıyla aynı kuralı izler: "2.5" reddedilir', async () => {
    const { api, user } = await renderPanel({}, makeEmptySettings());
    await user.click(screen.getByRole('button', { name: 'Gider ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni değişken gider' });
    await user.type(within(form).getByLabelText('Gider adı'), 'Komisyon dışı');
    await user.selectOptions(within(form).getByLabelText('Nasıl hesaplanır?'), 'satis_yuzdesi');
    await user.type(within(form).getByLabelText(/Oran/), '2.5');
    await user.click(within(form).getByRole('button', { name: SAVE }));
    expect(await within(form).findByText(/virgül kullanın \(örnek:/)).toBeInTheDocument();
    expect(api.writes()).toHaveLength(0);
  });
});

describe('AF-04, AF-05: metinler', () => {
  it("anlaşmalı kargo ipucu K08'e uygundur: bedel faturayla hakedişten düşer", async () => {
    const { user } = await renderPanel();
    await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
    expect(form).toHaveTextContent('Bedel, kargo faturasıyla hakedişinizden düşülür.');
    expect(form).not.toHaveTextContent('Trendyol öder');
    expect(form).toHaveTextContent('Trendyol kargo faturası kesmez.');
  });

  it('başlangıç tarihi önerisinin yaklaşık olduğu ve en eski siparişten önce seçilmesi gerektiği söylenir', async () => {
    const { user } = await renderPanel();
    await user.click(screen.getByRole('button', { name: 'Tarife ekle' }));
    const form = await screen.findByRole('form', { name: 'Yeni kargo tarifesi' });
    expect(form).toHaveTextContent('Önerilen tarih yaklaşıktır');
    expect(form).toHaveTextContent('en eski siparişten ÖNCE seçin');
    expect(form).toHaveTextContent('ve sonrasındaki siparişlerde kullanılır');
  });
});

describe('AF-10: rol ve hata metinleri', () => {
  it('rol yüklenirken yazma düğmeleri ve görüntüleyici notu çıkmaz', async () => {
    installFakeApi(routes({ 'GET /me': () => new Promise(() => undefined) }));
    render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
    await screen.findByRole('heading', { name: 'Kargo tarifesi' });
    expect(screen.queryByRole('button', { name: 'Tarife ekle' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Geri çek/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Ayarları görüntüleyebilirsiniz/)).not.toBeInTheDocument();
  });

  it('/me hata verirse arayüz engellemez (sunucu 403 esas)', async () => {
    installFakeApi(routes({ 'GET /me': { status: 500, body: problemBody('boom') } }));
    render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
    expect(await screen.findByRole('button', { name: 'Tarife ekle' })).toBeInTheDocument();
  });

  it('403 forbidden yetki metni verir, CSRF metni vermez', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/defaults`]: { status: 403, body: problemBody('forbidden', { status: 403 }) },
    });
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    const text = await screen.findByText(/Bu işlem için yetkiniz yok/);
    expect(text.closest('[role="alert"]')).not.toBeNull();
    expect(screen.queryByText(/İstek doğrulanamadı/)).not.toBeInTheDocument();
  });

  it('403 csrf-failed eski doğrulama metnini korur', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/defaults`]: { status: 403, body: problemBody('csrf-failed', { status: 403 }) },
    });
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    expect(await screen.findByText(/İstek doğrulanamadı/)).toBeInTheDocument();
  });

  it('401 oturum sona erdi metni verir', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/defaults`]: { status: 401, body: problemBody('unauthorized', { status: 401 }) },
    });
    const form = screen.getByRole('form', { name: 'Varsayılan desi' });
    await user.click(within(form).getByRole('button', { name: 'Kaydet' }));
    expect(await screen.findByText(/Oturumunuz sona erdi/)).toBeInTheDocument();
  });
});

describe('AF-08, AF-09, AF-13', () => {
  it('düzenlemede çizilmeyen alanın 422 hatası form başındaki hata satırına düşer', async () => {
    const { user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: {
        status: 422,
        body: {
          type: 'urn:netkar:problem:validation-error',
          status: 422,
          errors: [{ field: 'carrier', code: 'carrier_invalid' }],
        },
      },
    });
    await user.click(screen.getByRole('button', { name: /Düzenle: Trendyol Express/ }));
    const form = await screen.findByRole('form', { name: 'Kargo tarifesini düzenle' });
    await user.click(within(form).getByRole('button', { name: SAVE }));
    expect(
      await within(form).findByText('Bu kargo firması kullanılamaz. Listeden seçin.'),
    ).toBeInTheDocument();
  });

  it('seçenek grubu hatası alan yanında gösterilir ve gruba bağlanır', async () => {
    const { user } = await renderPanel(
      {
        [`PUT ${BASE}/cargo-tariffs`]: {
          status: 422,
          body: {
            type: 'urn:netkar:problem:validation-error',
            status: 422,
            errors: [{ field: 'price_includes_vat', code: 'decimal_invalid' }],
          },
        },
      },
      makeEmptySettings(),
    );
    const form = await fillNewTariff(user);
    await user.click(within(form).getByRole('button', { name: SAVE }));
    const message = await within(form).findByText('Geçerli bir sayı yazın.');
    const group = within(form).getByRole('group', { name: 'Fiyatları nasıl giriyorsunuz?' });
    expect(group.getAttribute('aria-describedby')).toContain(
      message.closest('[id]')?.getAttribute('id') ?? 'yok',
    );
  });

  it('ayar bölümleri adlandırılmış bölge (region) olarak duyurulur', async () => {
    await renderPanel();
    for (const name of [
      'Kargo tarifesi',
      'Platform hizmet bedeli tahmini',
      'Varsayılan desi',
      'Değişken giderler',
      'Ayar geçmişi',
    ]) {
      expect(screen.getByRole('region', { name })).toBeInTheDocument();
    }
  });

  it('kurulum adımları bölüme bağlantıdır; üçüncü adım "yakında" ve sayıya katılmaz', async () => {
    await renderPanel();
    expect(screen.getByText("2 adımdan 2'si tamam")).toBeInTheDocument();
    const links = screen.getAllByRole('link', { name: 'Kargo tarifesi' });
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['#kargo', '#kargo']);
    const fee = screen.getAllByRole('link', { name: 'Hizmet bedeli' });
    expect(fee.map((l) => l.getAttribute('href'))).toEqual(['#hizmet-bedeli', '#hizmet-bedeli']);
    const third = screen.getByText(/3\. Ürün maliyetleri/);
    expect(third).toHaveTextContent('Ürünler ekranında girilecek (yakında)');
  });

  it('bugün başlayan tarife girildiğinde geçmiş siparişler için tarife yok notu çıkar', async () => {
    await renderPanel({}, makeSettings({ cargo_tariffs: [makeTariff({ valid_from: TODAY })] }));
    expect(
      screen.getByText('Bugünden önceki siparişler için tarife yok; geçmiş raporlar eksik kalır.'),
    ).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------- AF-06: sözleşme

describe('AF-06: istek gövdeleri API şemasıyla uyumlu (statik beklenti listesi)', () => {
  it('panelin gönderdiği tüm gövdeler ve sorgular şemadaki alan adlarına uyar', async () => {
    const ok = (body: unknown) => ({ body });
    let tariffAttempt = 0;
    const { api, user } = await renderPanel({
      [`PUT ${BASE}/cargo-tariffs`]: () => {
        tariffAttempt += 1;
        return tariffAttempt === 1 ? past409('2026-08-10', 9) : TARIFF_OK;
      },
      [`PUT ${BASE}/service-fee-estimates`]: ok({
        ...makeWriteInfo({ revision: 11 }),
        created: true,
        estimate: makeFee(),
      }),
      [`POST ${BASE}/variable-expenses`]: {
        status: 201,
        body: { ...makeWriteInfo({ revision: 12 }), expense: makeExpense() },
      },
      [`PUT ${BASE}/variable-expenses/${EXPENSE_ID}`]: ok({
        ...makeWriteInfo({ revision: 13, action: 'replaced' }),
        expense: makeExpense(),
      }),
      [`PUT ${BASE}/defaults`]: ok({ ...makeWriteInfo({ revision: 14 }), default_desi: '4.00' }),
      [`DELETE ${BASE}/cargo-tariffs/${TARIFF_ID}`]: ok(makeWriteInfo({ action: 'retracted' })),
      [`DELETE ${BASE}/service-fee-estimates/${FEE_ID}`]: ok(
        makeWriteInfo({ action: 'retracted' }),
      ),
      [`DELETE ${BASE}/variable-expenses/${EXPENSE_ID}`]: ok(
        makeWriteInfo({ action: 'retracted' }),
      ),
    });

    // Kargo tarifesi: onaysız deneme, 409, onaylı gönderim
    const tariffForm = await fillNewTariff(user);
    await user.click(within(tariffForm).getByRole('button', { name: SAVE }));
    const dialog = await screen.findByRole('alertdialog', { name: 'Geçmiş raporlar değişecek' });
    await user.click(within(dialog).getByRole('button', { name: 'Değişikliği uygula' }));
    await screen.findByText(/Tarife eklendi/);

    // Hizmet bedeli
    await user.click(screen.getByRole('button', { name: 'Tahmin ekle' }));
    const feeForm = await screen.findByRole('form', { name: 'Yeni hizmet bedeli tahmini' });
    await user.type(within(feeForm).getByLabelText(/Sipariş başına tutar/), '12,50');
    await user.click(within(feeForm).getByRole('button', { name: SAVE }));
    await screen.findByText(/Hizmet bedeli tahmini eklendi/);

    // Gider: ekleme (tutar), düzenleme (yüzde)
    await user.click(screen.getByRole('button', { name: 'Gider ekle' }));
    const expenseForm = await screen.findByRole('form', { name: 'Yeni değişken gider' });
    await user.type(within(expenseForm).getByLabelText('Gider adı'), 'E-fatura');
    await user.type(within(expenseForm).getByLabelText(/Tutar \(KDV hariç/), '1,5');
    await user.click(within(expenseForm).getByRole('button', { name: SAVE }));
    await screen.findByText('Gider eklendi.');
    await user.click(screen.getByRole('button', { name: /Düzenle: Paketleme/ }));
    const editForm = await screen.findByRole('form', { name: 'Değişken gideri düzenle' });
    await user.selectOptions(within(editForm).getByLabelText('Nasıl hesaplanır?'), 'satis_yuzdesi');
    await user.type(within(editForm).getByLabelText(/Oran/), '2,5');
    await user.click(within(editForm).getByRole('button', { name: SAVE }));
    await screen.findByText('Gider güncellendi.');

    // Varsayılan desi
    const desiForm = screen.getByRole('form', { name: 'Varsayılan desi' });
    const desi = within(desiForm).getByLabelText('Varsayılan desi');
    await user.clear(desi);
    await user.type(desi, '4');
    await user.click(within(desiForm).getByRole('button', { name: 'Kaydet' }));
    await screen.findByText('Varsayılan desi kaydedildi.');

    // Üç geri çekme (istemci onayı + DELETE)
    for (const [name, label] of [
      [/Geri çek: Trendyol Express/, /Trendyol Express tarifesi geri çekildi/],
      [/Geri çek: 1 Ekim 2026 başlangıçlı tahmin/, /Hizmet bedeli sürümü geri çekildi/],
      [/Geri çek: Paketleme/, /Paketleme gideri geri çekildi/],
    ] as const) {
      await user.click(screen.getByRole('button', { name }));
      const confirm = await screen.findByRole('alertdialog');
      await user.click(within(confirm).getByRole('button', { name: 'Geri çek' }));
      await screen.findByText(label);
    }

    const writes = api.writes();
    const seenKeys = new Set<string>();
    for (const call of writes) {
      const after = call.path.slice(BASE.length);
      if (call.method === 'DELETE') {
        // Gövde yok; yalnız şemadaki sorgu parametreleri
        expect(call.body).toBeNull();
        for (const key of call.query.keys()) {
          expect(DELETE_QUERY_PARAMS as readonly string[]).toContain(key);
        }
        expect(call.query.has('confirm_past_change')).toBe(false);
        seenKeys.add(`DELETE ${after.split('/')[1]}`);
        continue;
      }
      const key = contractKeyOf(call.method, after);
      expect(key, `${call.method} ${after} sözleşmede tanımlı olmalı`).not.toBeNull();
      if (key === null) continue;
      const body = call.body as Record<string, unknown>;
      expect(bodyViolations(BODY_SPECS[key], body), `${call.method} ${after}`).toEqual([]);
      if (key === 'PUT /cargo-tariffs') expect(bracketViolations(body.brackets)).toEqual([]);
      // Çıplak onay alanı hiçbir istekte yoktur (YT-07)
      expect(body).not.toHaveProperty('confirm_past_change');
      seenKeys.add(key);
    }
    // Beş yazma ucu ve üç silme ucu gerçekten çalıştırıldı
    expect([...seenKeys].sort()).toEqual(
      [
        'DELETE cargo-tariffs',
        'DELETE service-fee-estimates',
        'DELETE variable-expenses',
        'POST /variable-expenses',
        'PUT /cargo-tariffs',
        'PUT /defaults',
        'PUT /service-fee-estimates',
      ].sort(),
    );
  });

  it('sözleşme denetleyicisi fazla alanı, eksik alanı ve biçim hatasını yakalar', () => {
    const spec = BODY_SPECS['PUT /service-fee-estimates'];
    expect(
      bodyViolations(spec, {
        valid_from: '2026-10-01',
        amount: '12.00',
        amount_includes_vat: true,
        expected_revision: 3,
      }),
    ).toEqual([]);
    expect(
      bodyViolations(spec, {
        valid_from: '2026-10-01',
        amount: 12,
        amount_includes_vat: true,
        x: 1,
      }),
    ).toEqual(['x: şemada yok (extra="forbid" 422 verir)', 'amount: sade ondalık dizge olmalı']);
    expect(bodyViolations(spec, { valid_from: '1 Ekim' })).toContain('amount: zorunlu alan eksik');
    // TypeScript gövde türleri de aynı alan adlarını taşır
    const check: RecordedCall['body'] = { default_desi: null };
    expect(bodyViolations(BODY_SPECS['PUT /defaults'], check as Record<string, unknown>)).toEqual(
      [],
    );
  });
});
