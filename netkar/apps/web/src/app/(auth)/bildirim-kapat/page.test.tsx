import { describe, expect, it } from 'vitest';

import UnsubscribePage, { metadata } from './page';

describe('/bildirim-kapat sayfası', () => {
  it('noindex ve no-referrer üst verisi taşır', () => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.referrer).toBe('no-referrer');
  });

  it('token almaz (sunucu çıktısına girmez): bileşen prop taşımaz, oturum sorgulanmaz', () => {
    const element = UnsubscribePage() as { props: Record<string, unknown> };
    expect(element.props).toEqual({});
  });
});
