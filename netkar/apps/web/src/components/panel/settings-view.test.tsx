import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SettingsContent } from '@/components/panel/settings-view';
import { makeCarriers, makeHistory, makeSettings } from '@/lib/profit/settings-fixtures';
import { ACCOUNT_ID, makeAccounts } from '@/lib/profit/test-fixtures';
import { mockFetch, problem } from '@/test/api-mock';

afterEach(() => {
  vi.unstubAllGlobals();
});

const accountsPath = '/api/v1/marketplace-accounts';
const settingsPath = `/api/v1/marketplace-accounts/${ACCOUNT_ID}/profit-settings`;

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

  it('bağlı mağaza varsa kâr ayarları formu açılır, yakında metni kalmaz', async () => {
    mockFetch(
      (url) => (url.pathname === accountsPath ? { body: makeAccounts() } : undefined),
      (url) => (url.pathname === `${settingsPath}` ? { body: makeSettings() } : undefined),
      (url) => (url.pathname === `${settingsPath}/carriers` ? { body: makeCarriers() } : undefined),
      (url) => (url.pathname === `${settingsPath}/history` ? { body: makeHistory() } : undefined),
      (url) => (url.pathname === '/api/v1/me' ? { body: { role: 'owner' } } : undefined),
    );
    render(<SettingsContent />);
    expect(await screen.findByRole('heading', { name: 'Kargo tarifesi' })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: 'Platform hizmet bedeli tahmini' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/çok yakında/)).not.toBeInTheDocument();
    // Mağaza bağlantı durumu kartı korunur
    expect(screen.getByText('Satıcı numarası:')).toBeInTheDocument();
  });

  it('bağlı mağaza yoksa kâr ayarları açılmadan önce mağaza bağlama yönlendirmesi var', async () => {
    mockFetch((url) => (url.pathname === accountsPath ? { body: [] } : undefined));
    render(<SettingsContent />);
    expect(
      await screen.findByText('Kâr ayarları mağazanızı bağlayınca açılır'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Kargo tarifesi' })).not.toBeInTheDocument();
  });
});
