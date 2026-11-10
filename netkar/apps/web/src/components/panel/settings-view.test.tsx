import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SettingsContent } from '@/components/panel/settings-view';
import { makeAccounts } from '@/lib/profit/test-fixtures';
import { mockFetch, problem } from '@/test/api-mock';

afterEach(() => {
  vi.unstubAllGlobals();
});

const accountsPath = '/api/v1/marketplace-accounts';

describe('Ayarlar içeriği (UX-02)', () => {
  it('bağlı mağaza varsa "Bağlı değil" yazmaz, gerçek durumu gösterir', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? { body: makeAccounts() } : undefined));
    render(<SettingsContent />);
    expect(await screen.findByText('Bağlı', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByText('Bağlı değil')).not.toBeInTheDocument();
    expect(screen.getByText('123456')).toBeInTheDocument();
    // Bağlıyken bağlantı diyaloğu düğmesi yok
    expect(
      screen.queryByRole('button', { name: 'Trendyol mağazasını bağla' }),
    ).not.toBeInTheDocument();
  });

  it('bağlı mağaza yoksa "Bağlı değil" ve bağlantı düğmesi', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? { body: [] } : undefined));
    render(<SettingsContent />);
    expect(await screen.findByText('Bağlı değil')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Trendyol mağazasını bağla' })).toBeInTheDocument();
  });

  it('pasif hesap bağlı sayılmaz', async () => {
    mockFetch((url) =>
      url.pathname === accountsPath
        ? { body: [{ ...makeAccounts()[0], status: 'disabled' }] }
        : undefined,
    );
    render(<SettingsContent />);
    expect(await screen.findByText('Bağlı değil')).toBeInTheDocument();
  });

  it('yüklenirken kesin durum yazmaz', () => {
    mockFetch(() => undefined);
    render(<SettingsContent />);
    expect(screen.getByText('Kontrol ediliyor')).toBeInTheDocument();
    expect(screen.queryByText('Bağlı değil')).not.toBeInTheDocument();
  });

  it('hata durumunda tekrar dene sunar, sabit durum yazmaz', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? problem(503, 'busy') : undefined));
    render(<SettingsContent />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Rapor şu an yoğun');
    expect(screen.getByRole('button', { name: 'Tekrar dene' })).toBeInTheDocument();
    expect(screen.queryByText('Bağlı değil')).not.toBeInTheDocument();
    // Y-10: hata durumunda "mağazanızı bağlayın" açıklaması yok
    expect(screen.queryByText(/mağazanızı bağlayın/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ilk kârınızı/)).not.toBeInTheDocument();
  });

  it('bağlı mağaza yoksa bağlama açıklaması, bağlıysa bağlı açıklaması; rozet bilgi tonundadır', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? { body: [] } : undefined));
    const { unmount } = render(<SettingsContent />);
    expect(await screen.findByText(/Trendyol mağazanızı bağlayın/)).toBeInTheDocument();
    unmount();

    mockFetch((url) => (url.pathname === accountsPath ? { body: makeAccounts() } : undefined));
    render(<SettingsContent />);
    const badge = await screen.findByText('Bağlı', { selector: 'span' });
    // Kâr yeşili değil bilgi tonu: bağlantı durumu kâr anlamı taşımaz
    expect(badge.className).toContain('text-info');
    expect(badge.className).not.toContain('text-profit');
    expect(screen.getByText('Mağazanız bağlı. Bağlantı yalnız okuma yapar.')).toBeInTheDocument();
    expect(screen.queryByText(/mağazanızı bağlayın/)).not.toBeInTheDocument();
  });

  it('kargo tarifesi ve hizmet bedeli bölümünün yakında olduğunu dürüstçe söyler', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? { body: makeAccounts() } : undefined));
    render(<SettingsContent />);
    const region = screen.getByRole('region', { name: 'Kargo tarifesi ve hizmet bedeli' });
    expect(region).toHaveTextContent('Kargo tarifesi ve hizmet bedeli girişi çok yakında');
    expect(region).toHaveTextContent('Bu bölüm henüz açılmadı');
    // Y-2: ayar ekranı bilinen kâr rakamı varmış gibi konuşmaz
    expect(region).not.toHaveTextContent('bilinen giderlerle');
    await screen.findByText('Bağlı', { selector: 'span' });
  });
});
