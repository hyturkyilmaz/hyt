import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WaitlistForm } from './waitlist-form';

function mockFetch(status: number, body: unknown = { status: 'ok' }) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe('bekleme listesi formu', () => {
  it('ticari ileti onay kutusu varsayılan olarak işaretsizdir ve KVKK bağlantısı vardır', () => {
    render(<WaitlistForm />);
    expect(screen.getByRole('checkbox', { name: /ticari elektronik ileti/ })).not.toBeChecked();
    expect(screen.getByRole('link', { name: /KVKK aydınlatma metninde/ })).toHaveAttribute(
      'href',
      '/kvkk-aydinlatma-metni',
    );
    expect(screen.getByLabelText(/Mağaza kategoriniz/)).toBeInTheDocument();
  });

  it('boş gönderimde hata gösterir, alana odaklanır ve ağ çağrısı yapmaz', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<WaitlistForm />);
    await user.click(screen.getByRole('button', { name: 'Bekleme listesine katıl' }));
    expect(await screen.findByText(/E-posta adresinizi yazın/)).toBeInTheDocument();
    expect(screen.getByText(/aralığınızı seçin/)).toBeInTheDocument();
    expect(screen.getByLabelText('E-posta')).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('geçerli gönderimde uç noktaya JSON yazar; onay verilmediyse false gider', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<WaitlistForm />);
    await user.type(screen.getByLabelText('E-posta'), 'ornek@magaza.com');
    await user.selectOptions(screen.getByLabelText('Aylık sipariş sayınız'), '100-1000');
    await user.click(screen.getByRole('button', { name: 'Bekleme listesine katıl' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/bekleme-listesi');
    expect(JSON.parse(String(init.body))).toEqual({
      email: 'ornek@magaza.com',
      monthlyOrders: '100-1000',
      marketingConsent: false,
      website: '',
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Kaydınız alındı');
  });

  it('onay kutusu işaretlenirse true gider, kategori seçilirse eklenir', async () => {
    const fetchMock = mockFetch(200);
    const user = userEvent.setup();
    render(<WaitlistForm />);
    await user.type(screen.getByLabelText('E-posta'), 'a@b.co');
    await user.selectOptions(screen.getByLabelText('Aylık sipariş sayınız'), 'yok');
    await user.selectOptions(screen.getByLabelText(/Mağaza kategoriniz/), 'giyim');
    await user.click(screen.getByRole('checkbox', { name: /ticari elektronik ileti/ }));
    await user.click(screen.getByRole('button', { name: 'Bekleme listesine katıl' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      marketingConsent: true,
      storeCategory: 'giyim',
    });
  });

  it('sunucu hatasında ayrıntı sızdırmadan Türkçe uyarı verir ve yeniden denemeye izin verir', async () => {
    mockFetch(503, { type: 'urn:netkar:problem:waitlist-unavailable' });
    const user = userEvent.setup();
    render(<WaitlistForm />);
    await user.type(screen.getByLabelText('E-posta'), 'a@b.co');
    await user.selectOptions(screen.getByLabelText('Aylık sipariş sayınız'), 'yok');
    await user.click(screen.getByRole('button', { name: 'Bekleme listesine katıl' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/şu an alınamıyor/);
    expect(screen.getByRole('button', { name: 'Bekleme listesine katıl' })).toBeEnabled();
  });

  it('ağ hatasında bağlantı mesajı gösterir', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('ağ'))),
    );
    const user = userEvent.setup();
    render(<WaitlistForm />);
    await user.type(screen.getByLabelText('E-posta'), 'a@b.co');
    await user.selectOptions(screen.getByLabelText('Aylık sipariş sayınız'), 'yok');
    await user.click(screen.getByRole('button', { name: 'Bekleme listesine katıl' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/Bağlantı kurulamadı/);
  });
});
