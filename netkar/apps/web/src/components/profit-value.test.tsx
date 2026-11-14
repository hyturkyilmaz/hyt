import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ProfitValue } from '@/components/profit-value';

describe('ProfitValue', () => {
  it('pozitif değeri kâr olarak işaretler (renk, ikon, ekran okuyucu metni)', () => {
    const { container } = render(<ProfitValue value="1842.30" />);
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute('data-sign', 'positive');
    expect(root).toHaveClass('text-profit');
    expect(root.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('Kâr:', { exact: false })).toHaveClass('sr-only');
    expect(root).toHaveTextContent('Kâr: ₺1.842,30');
  });

  it('negatif değeri zarar olarak işaretler ve eksi işaretini gösterir', () => {
    const { container } = render(<ProfitValue value="-212.40" />);
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute('data-sign', 'negative');
    expect(root).toHaveClass('text-loss');
    expect(root).toHaveTextContent('Zarar: -₺212,40');
    expect(root.querySelector('svg')).not.toBeNull();
  });

  it('sıfırı nötr gösterir', () => {
    const { container } = render(<ProfitValue value="0" />);
    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveAttribute('data-sign', 'zero');
    expect(root).toHaveClass('text-muted-foreground');
    expect(root).toHaveTextContent('Kâr zarar yok: ₺0,00');
  });

  it('kuruşa yuvarlandığında sıfır olan negatifi zarar saymaz', () => {
    const { container } = render(<ProfitValue value="-0.003" />);
    expect(container.firstElementChild).toHaveAttribute('data-sign', 'zero');
  });

  it('yüzde modunda yüzde biçimini kullanır', () => {
    const { container } = render(<ProfitValue value="-4.5" kind="percent" />);
    expect(container.firstElementChild).toHaveTextContent('Zarar: -%4,5');
  });

  it('ikon gizlenebilir; ekran okuyucu metni kalır', () => {
    const { container } = render(<ProfitValue value="5" hideIcon />);
    expect(container.querySelector('svg')).toBeNull();
    expect(container.firstElementChild).toHaveTextContent('Kâr: ₺5,00');
  });
});
