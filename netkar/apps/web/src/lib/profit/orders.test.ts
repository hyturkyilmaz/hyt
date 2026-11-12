import { describe, expect, it } from 'vitest';

import { orderBadges, orderNetView, orderProductTitle } from '@/lib/profit/orders';
import {
  ORDER_FILTER_OPTIONS,
  defaultOrderSortFor,
  isValidOrderSearch,
  orderQueryString,
  ordersHref,
  parseOrderQuery,
} from '@/lib/profit/query';
import { makeOrderItem } from '@/lib/profit/test-fixtures';

const params = (text: string) => new URLSearchParams(text);

describe('orderNetView', () => {
  it('iptal siparişte rakam yok, asla 0,00 değil', () => {
    const view = orderNetView(
      makeOrderItem({
        cancelled: true,
        net_profit: null,
        net_sales_excl_vat: null,
        known_expenses_profit: null,
        certainty: 'iptal',
      }),
    );
    expect(view).toEqual({ kind: 'cancelled' });
  });

  it('değer varsa değer; sıfır da değerdir', () => {
    expect(orderNetView(makeOrderItem({ net_profit: '0.00' }))).toEqual({
      kind: 'value',
      value: '0.00',
    });
  });

  it('null net kâr hesaplanamadı: eksik kalemler ve etiketli bilinen kâr', () => {
    const view = orderNetView(
      makeOrderItem({
        net_profit: null,
        known_expenses_profit: '75.00',
        missing_items: ['kargo_gonderi', 'platform_hizmet_bedeli'],
        certainty: 'eksik',
      }),
    );
    expect(view).toEqual({
      kind: 'uncomputable',
      missing: ['kargo', 'hizmet bedeli'],
      known: '75.00',
    });
  });

  it('net kâr null ama bilinen giderlerle zarar kesin: "en az" zarar', () => {
    const view = orderNetView(
      makeOrderItem({
        net_profit: null,
        known_expenses_profit: '-12.00',
        loss_reason: 'known_expenses',
        missing_items: ['kargo_gonderi'],
        certainty: 'eksik',
      }),
    );
    expect(view.kind).toBe('loss');
    if (view.kind === 'loss') {
      expect(view.loss).toMatchObject({ magnitude: '12.00', amount: '-12.00', exact: false });
      expect(view.loss.note).toBe('Kargo düşülünce bu rakam azalır.');
    }
  });
});

describe('orderBadges ve ürün adı', () => {
  it('zarar, kesinlik, ekstre ve beklenmeyen kesinti rozetleri; eksik kesinlik rozeti basılmaz', () => {
    const badges = orderBadges(
      makeOrderItem({
        net_profit: '-30.00',
        loss_reason: 'net_profit',
        certainty: 'tahmini',
        awaiting_payout: true,
        unexpected_deduction: true,
      }),
    );
    expect(badges.map((b) => b.label)).toEqual([
      'Zarar',
      'Tahmini',
      'Ekstresi gelmedi',
      'Beklenmeyen kesinti',
    ]);
    expect(orderBadges(makeOrderItem({ certainty: 'eksik' }))).toEqual([]);
    expect(orderBadges(makeOrderItem({ cancelled: true, certainty: 'iptal' }))).toEqual([]);
  });

  it('katalogda adı olmayan ürün "Başlıksız ürün" olur', () => {
    expect(orderProductTitle({ barcode: 'B', title: null })).toBe('Başlıksız ürün');
    expect(orderProductTitle({ barcode: 'B', title: '   ' })).toBe('Başlıksız ürün');
    expect(orderProductTitle({ barcode: 'B', title: 'Ad' })).toBe('Ad');
  });
});

describe('sipariş sorgusu', () => {
  it('süzgeç etiketleri: "Ekstresi gelmeyen", "hakediş bekleyen" değil', () => {
    expect(ORDER_FILTER_OPTIONS.map((o) => o.label)).toEqual([
      'Tümü',
      'Zarar edenler',
      'Ekstresi gelmeyen',
      'Beklenmeyen kesinti',
    ]);
  });

  it('zarar süzgecinde varsayılan sıra net kâr artan; diğerlerinde tarih azalan', () => {
    expect(defaultOrderSortFor('loss')).toEqual({ sort: 'net_profit', order: 'asc' });
    expect(defaultOrderSortFor('awaiting_payout')).toEqual({ sort: 'date', order: 'desc' });
    expect(parseOrderQuery(params('filter=loss'))).toMatchObject({
      sort: 'net_profit',
      order: 'asc',
      filter: 'loss',
      range: '30d',
      q: '',
    });
  });

  it('geçersiz değerler varsayılana düşer; arama API desenine uyar', () => {
    expect(parseOrderQuery(params('filter=x&sort=y&order=z&range=q&q=%3Cb%3E'))).toEqual({
      range: '30d',
      sort: 'date',
      order: 'desc',
      filter: 'all',
      q: '',
    });
    expect(parseOrderQuery(params('q=%2010004%20')).q).toBe('10004');
    expect(isValidOrderSearch('A-1.b_2')).toBe(true);
    expect(isValidOrderSearch('.1')).toBe(false);
    expect(isValidOrderSearch('a b')).toBe(false);
    expect(isValidOrderSearch('1'.repeat(65))).toBe(false);
  });

  it('sorgu dizesi yalnız varsayılandan farklıyı yazar', () => {
    expect(orderQueryString(parseOrderQuery(params('')))).toBe('range=30d');
    expect(orderQueryString(parseOrderQuery(params('filter=loss&range=7d')))).toBe(
      'range=7d&filter=loss',
    );
    expect(orderQueryString(parseOrderQuery(params('q=10004&filter=awaiting_payout')))).toBe(
      'range=30d&filter=awaiting_payout&q=10004',
    );
    expect(ordersHref({ range: '7d', filter: 'loss' })).toBe(
      '/panel/siparisler?range=7d&filter=loss',
    );
    expect(ordersHref({ range: '7d', q: '10004' })).toBe('/panel/siparisler?range=7d&q=10004');
  });
});
