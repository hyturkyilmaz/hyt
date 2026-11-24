import { describe, expect, it } from 'vitest';

import { describeRateLimitWait, describeWait } from '@/lib/api/retry-after';

describe('describeWait', () => {
  it.each([
    [0, 'birkaç saniye sonra'],
    [1, 'birkaç saniye sonra'],
    [59, 'birkaç saniye sonra'],
    [60, 'yaklaşık 1 dakika sonra'],
    [61, 'yaklaşık 2 dakika sonra'],
    [89, 'yaklaşık 2 dakika sonra'],
    [900, 'yaklaşık 15 dakika sonra'],
    [3412, 'yaklaşık 57 dakika sonra'],
    [3540, 'yaklaşık 59 dakika sonra'],
    [3541, 'yaklaşık 1 saat sonra'],
    [3599, 'yaklaşık 1 saat sonra'],
    [3600, 'yaklaşık 1 saat sonra'],
    [3601, 'yaklaşık 2 saat sonra'],
    [5399, 'yaklaşık 2 saat sonra'],
    [43200, 'yaklaşık 12 saat sonra'],
    [86400, 'yaklaşık 24 saat sonra'],
    [86401, 'yaklaşık 2 gün sonra'],
    [172800, 'yaklaşık 2 gün sonra'],
    [172801, 'yaklaşık 3 gün sonra'],
  ])('%i sn -> %s', (seconds, expected) => {
    expect(describeWait(seconds)).toBe(expected);
  });

  it('geçersiz süre için null döner', () => {
    expect(describeWait(undefined)).toBeNull();
    expect(describeWait(-5)).toBeNull();
    expect(describeWait(Number.NaN)).toBeNull();
    expect(describeWait(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('describeRateLimitWait', () => {
  it('cümleyi büyük harfle başlatır', () => {
    expect(describeRateLimitWait(43200)).toBe(
      'Çok fazla deneme yaptınız. Yaklaşık 12 saat sonra tekrar deneyin.',
    );
    expect(describeRateLimitWait(30)).toBe(
      'Çok fazla deneme yaptınız. Birkaç saniye sonra tekrar deneyin.',
    );
    expect(describeRateLimitWait(90000)).toBe(
      'Çok fazla deneme yaptınız. Yaklaşık 2 gün sonra tekrar deneyin.',
    );
  });

  it('süre yoksa null döner', () => {
    expect(describeRateLimitWait(undefined)).toBeNull();
  });
});
