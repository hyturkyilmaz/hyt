import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CommissionCalculator } from './commission-calculator';
import { DesiCalculator } from './desi-calculator';
import { ProfitCalculator } from './profit-calculator';

const NBSP = String.fromCharCode(32);

describe('komisyon hesaplayıcısı', () => {
  it('örnek değerlerle ilk açılışta sonuç gösterir ve "örnek" etiketi taşır', () => {
    render(<CommissionCalculator />);
    expect(screen.getByText('Örnek değerler')).toBeInTheDocument();
    // 600 TL, %20 KDV, %21 komisyon: komisyon 126,00; hakediş 474,00; stopaj 5,00; tahsilat 469,00
    const table = screen.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' });
    expect(within(table).getByRole('row', { name: /Toplam komisyon/ })).toHaveTextContent(
      `-126,00${NBSP}TL`,
    );
    expect(within(table).getByRole('row', { name: /Hakediş/ })).toHaveTextContent(
      `474,00${NBSP}TL`,
    );
    expect(within(table).getByRole('row', { name: /Hesabınıza geçecek/ })).toHaveTextContent(
      `469,00${NBSP}TL`,
    );
  });

  it('girdi değişince sonuç güncellenir, virgül ve nokta ondalığı kabul edilir', async () => {
    const user = userEvent.setup();
    render(<CommissionCalculator />);
    const price = screen.getByLabelText('Satış fiyatı (KDV dahil)');
    await user.clear(price);
    await user.type(price, '1.000,00');
    expect(screen.queryByText('Örnek değerler')).not.toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' });
    expect(within(table).getByRole('row', { name: /Toplam komisyon/ })).toHaveTextContent(
      `-210,00${NBSP}TL`,
    );
    await user.clear(price);
    await user.type(price, '1000.5');
    // Girdi geçersizken tablo yeniden kurulur; güncel tabloyu yeniden bul
    const updated = screen.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' });
    // 1000,50 x %21 = 210,105 -> 210,11; hakediş 790,39
    expect(within(updated).getByRole('row', { name: /Hakediş/ })).toHaveTextContent(
      `790,39${NBSP}TL`,
    );
  });

  it('geçersiz girdide alan hatası, aria-invalid ve açıklayıcı mesaj gösterir', async () => {
    const user = userEvent.setup();
    render(<CommissionCalculator />);
    const price = screen.getByLabelText('Satış fiyatı (KDV dahil)');
    await user.clear(price);
    await user.type(price, 'abc');
    expect(price).toHaveAttribute('aria-invalid', 'true');
    const describedBy = price.getAttribute('aria-describedby') ?? '';
    const message = describedBy
      .split(' ')
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    expect(message).toMatch(/Sayı olarak yazın/);
    expect(screen.getByText('Sonucu görmek için alanları düzeltin')).toBeInTheDocument();
  });

  it('KDV varsayımı değiştirilince karşılaştırma farkını yazar', async () => {
    const user = userEvent.setup();
    render(<CommissionCalculator />);
    // 600 TL, %21: KDV hariç varsayımda komisyon 126 + 25,20 = 151,20; fark 25,20
    expect(screen.getByText(/aradaki fark/)).toHaveTextContent(`25,20${NBSP}TL`);
    await user.selectOptions(
      screen.getByLabelText('Komisyon tutarı'),
      'KDV hariç, üstüne KDV eklenir',
    );
    const table = screen.getByRole('table', { name: 'Komisyon ve kesinti kırılımı' });
    expect(within(table).getByRole('row', { name: /Toplam komisyon/ })).toHaveTextContent(
      `-151,20${NBSP}TL`,
    );
  });
});

describe('kâr hesaplayıcısı', () => {
  it('örnek değerlerle net kâr ve başabaş fiyatı gösterir', () => {
    render(<ProfitCalculator />);
    const table = screen.getByRole('table', { name: 'Net kâr kırılımı' });
    // Net satış 500; maliyet 250; komisyon 105; kargo 60 -> iade öncesi 85,00; %5 iade payı
    expect(within(table).getByRole('row', { name: /İade öncesi net kâr/ })).toHaveTextContent(
      `85,00${NBSP}TL`,
    );
    expect(within(table).getByRole('row', { name: /Başabaş satış fiyatı/ })).toBeInTheDocument();
    expect(screen.getByText('Ürün başına tahmini net kâr')).toBeInTheDocument();
  });

  it('maliyet satıştan yüksekse uyarı gösterir, zarar işaretiyle belirtilir', async () => {
    const user = userEvent.setup();
    render(<ProfitCalculator />);
    const cost = screen.getByLabelText(/Alış maliyeti/);
    await user.clear(cost);
    await user.type(cost, '900');
    expect(screen.getByText(/Alış maliyeti satış fiyatının/)).toBeInTheDocument();
    expect(screen.getAllByText('Zarar:', { exact: false }).length).toBeGreaterThan(0);
  });

  it('ROAS girişine geçince ROAS alanı görünür ve boşsa hata verir', async () => {
    const user = userEvent.setup();
    render(<ProfitCalculator />);
    await user.selectOptions(screen.getByLabelText('Reklam girişi'), 'ROAS');
    const roas = screen.getByLabelText('ROAS');
    expect(roas).toHaveAttribute('aria-invalid', 'true');
    await user.type(roas, '5');
    expect(roas).not.toHaveAttribute('aria-invalid');
  });

  it('sonuç alanı aria-live ile duyurulur', () => {
    render(<ProfitCalculator />);
    const result = screen.getByRole('table', { name: 'Net kâr kırılımı' }).closest('[aria-live]');
    expect(result).toHaveAttribute('aria-live', 'polite');
  });
});

describe('desi hesaplayıcısı', () => {
  it('örnek: 30x20x10 cm, 1 kg -> 2,00 desi', () => {
    render(<DesiCalculator />);
    const table = screen.getByRole('table', { name: 'Desi sonucu' });
    expect(within(table).getByRole('row', { name: /^Hacimsel desi/ })).toHaveTextContent('2,00');
    expect(within(table).getByRole('row', { name: /Ücretlendirmeye esas/ })).toHaveTextContent(
      '2,00',
    );
  });

  it('ağırlık büyükse ağırlığı esas alır', async () => {
    const user = userEvent.setup();
    render(<DesiCalculator />);
    const weight = screen.getByLabelText(/Ağırlık/);
    await user.clear(weight);
    await user.type(weight, '5,5');
    const table = screen.getByRole('table', { name: 'Desi sonucu' });
    expect(within(table).getByRole('row', { name: /Ücretlendirmeye esas/ })).toHaveTextContent(
      'ağırlık esas alınır',
    );
  });

  it('küçültme tablosunu gösterir', () => {
    render(<DesiCalculator />);
    expect(screen.getByRole('table', { name: 'Koli küçülürse desi değişimi' })).toBeInTheDocument();
  });
});
