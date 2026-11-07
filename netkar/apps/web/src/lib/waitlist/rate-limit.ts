// Küçük, bellek içi sabit pencere sınırlayıcı. Tek süreç içindir; gerçek kayıt uç noktası
// API'ye geçtiğinde sınır API'deki ortak rate limit'e taşınır (ADR-0001).

export interface RateLimiter {
  /** İzin verilirse true; aksi halde kalan bekleme süresini (sn) negatif olmayan sayı olarak verir. */
  check(key: string): { allowed: true } | { allowed: false; retryAfterSeconds: number };
}

export function createRateLimiter(options: {
  limit: number;
  windowMs: number;
  now?: () => number;
}): RateLimiter {
  const { limit, windowMs, now = Date.now } = options;
  const buckets = new Map<string, { start: number; count: number }>();

  return {
    check(key) {
      const current = now();
      // Bellek şişmesin: süresi dolan kovaları ara sıra temizle
      if (buckets.size > 1000) {
        for (const [bucketKey, bucket] of buckets) {
          if (current - bucket.start >= windowMs) buckets.delete(bucketKey);
        }
      }
      const bucket = buckets.get(key);
      if (!bucket || current - bucket.start >= windowMs) {
        buckets.set(key, { start: current, count: 1 });
        return { allowed: true };
      }
      if (bucket.count < limit) {
        bucket.count += 1;
        return { allowed: true };
      }
      return {
        allowed: false,
        retryAfterSeconds: Math.max(1, Math.ceil((bucket.start + windowMs - current) / 1000)),
      };
    },
  };
}
