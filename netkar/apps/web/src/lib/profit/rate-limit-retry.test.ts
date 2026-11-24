import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';
import { retryOnceOnRateLimit } from '@/lib/profit/rate-limit-retry';

describe('retryOnceOnRateLimit (Y-8)', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('429 sonrası Retry-After kadar bekler ve bir kez yeniden dener', async () => {
    const request = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new ApiError({ status: 429, retryAfterSeconds: 2 }))
      .mockResolvedValueOnce('tamam');
    const result = retryOnceOnRateLimit(request);
    await vi.advanceTimersByTimeAsync(1999);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toBe('tamam');
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('ikinci 429 yükselir, üçüncü deneme yapılmaz', async () => {
    const request = vi
      .fn<() => Promise<string>>()
      .mockRejectedValue(new ApiError({ status: 429, retryAfterSeconds: 1 }));
    const result = retryOnceOnRateLimit(request);
    const assertion = expect(result).rejects.toBeInstanceOf(ApiError);
    await vi.advanceTimersByTimeAsync(1000);
    await assertion;
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('429 dışı hatada beklemez ve yeniden denemez', async () => {
    const request = vi.fn<() => Promise<string>>().mockRejectedValue(new ApiError({ status: 503 }));
    await expect(retryOnceOnRateLimit(request)).rejects.toMatchObject({ status: 503 });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('çok uzun Retry-After beklenmez', async () => {
    const request = vi
      .fn<() => Promise<string>>()
      .mockRejectedValue(new ApiError({ status: 429, retryAfterSeconds: 600 }));
    await expect(retryOnceOnRateLimit(request)).rejects.toMatchObject({ status: 429 });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('bekleme sırasında iptal edilirse yeniden denemez', async () => {
    const controller = new AbortController();
    const request = vi
      .fn<() => Promise<string>>()
      .mockRejectedValue(new ApiError({ status: 429, retryAfterSeconds: 5 }));
    const result = retryOnceOnRateLimit(request, controller.signal);
    const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(100);
    controller.abort();
    await assertion;
    expect(request).toHaveBeenCalledTimes(1);
  });
});
