import { describe, expect, it } from 'vitest';

import { toSubscriptionBody, urlBase64ToUint8Array } from '@/lib/push/browser';

describe('urlBase64ToUint8Array', () => {
  it('dolgusuz base64url değeri baytlara çevirir', () => {
    expect(Array.from(urlBase64ToUint8Array('AQID'))).toEqual([1, 2, 3]);
    expect(Array.from(urlBase64ToUint8Array('-_8'))).toEqual([251, 255]);
  });

  it('geçersiz karakteri reddeder', () => {
    expect(() => urlBase64ToUint8Array('a+b/')).toThrow();
    expect(() => urlBase64ToUint8Array('a b')).toThrow();
    expect(() => urlBase64ToUint8Array('')).toThrow();
  });
});

describe('toSubscriptionBody', () => {
  const sub = (json: unknown) => ({ toJSON: () => json }) as unknown as PushSubscription;

  it('uç nokta ve anahtarları alır, fazla alanları (expirationTime) atar', () => {
    expect(
      toSubscriptionBody(
        sub({
          endpoint: 'https://fcm.googleapis.com/x',
          expirationTime: null,
          keys: { p256dh: 'p', auth: 'a' },
        }),
      ),
    ).toEqual({ endpoint: 'https://fcm.googleapis.com/x', keys: { p256dh: 'p', auth: 'a' } });
  });

  it('eksik abonelikte hata atar', () => {
    expect(() => toSubscriptionBody(sub({ endpoint: 'https://x' }))).toThrow();
    expect(() => toSubscriptionBody(sub({ keys: { p256dh: 'p', auth: 'a' } }))).toThrow();
  });
});
