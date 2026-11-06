// Gerçek istemci IP'sinin API'ye güvenilir biçimde iletilmesi (ADR-0002, denetim Y-01).
//
// Sorun: Next.js rewrites vekili istemcinin gönderdiği X-Forwarded-For/X-Real-IP başlıklarını API'ye
// olduğu gibi geçirir ve kendi XFF girdisini eklemez. Bu yüzden başlığı istemci yazar; API de
// rate limit kovasını sahte değerle değiştirir. Çözüm: middleware, /api/* isteklerinde istemciden
// gelen tüm IP başlıklarını SİLER ve yalnız dağıtımın seçtiği TEK kaynaktan çıkardığı doğrulanmış
// IP'yi tek bir X-Forwarded-For değeri olarak yazar. API yalnız bu web ağından gelen
// bağlantıda başlığı okur (TRUSTED_PROXY_CIDRS / TRUSTED_PROXY_HOPS).
//
// Kaynak (CLIENT_IP_SOURCE), dağıtım topolojisine göre TEK olarak seçilir:
//   none              : (varsayılan) hiçbir başlığa güvenilmez; API'ye IP iletilmez. Yerel geliştirme.
//   cf-connecting-ip  : Cloudflare arkasında. Köken yalnız Cloudflare aralıklarına açık olmalı;
//                       aksi halde başlığı herkes yazabilir.
//   x-forwarded-for   : XFF ekleyen bir vekil (ör. Traefik) arkasında; sağdan CLIENT_IP_TRUSTED_HOPS.
//                       Sol taraf istemci kontrolünde olduğu için hiç okunmaz.

export const CLIENT_IP_SOURCES = ['none', 'cf-connecting-ip', 'x-forwarded-for'] as const;
export type ClientIpSource = (typeof CLIENT_IP_SOURCES)[number];

export interface ClientIpConfig {
  source: ClientIpSource;
  /** Yalnız `x-forwarded-for` kaynağı için: sağdan sayılan güvenilir vekil sayısı. */
  hops: number;
}

// API'ye istemciden olduğu gibi geçmemesi gereken, istemci IP'si taşıyabilen başlıklar.
export const CLIENT_IP_HEADERS = [
  'x-forwarded-for',
  'x-real-ip',
  'cf-connecting-ip',
  'true-client-ip',
  'x-client-ip',
  'x-cluster-client-ip',
  'fastly-client-ip',
  'forwarded',
] as const;

export const FORWARDED_FOR_HEADER = 'x-forwarded-for';
const MAX_HOPS = 10;

export function parseClientIpConfig(source: Record<string, string | undefined>): ClientIpConfig {
  const rawSource = source.CLIENT_IP_SOURCE?.trim().toLowerCase() || 'none';
  if (!(CLIENT_IP_SOURCES as readonly string[]).includes(rawSource)) {
    throw new Error(
      `CLIENT_IP_SOURCE geçersiz: ${CLIENT_IP_SOURCES.join(', ')} değerlerinden biri olmalı`,
    );
  }
  const rawHops = source.CLIENT_IP_TRUSTED_HOPS?.trim() || '1';
  const hops = Number(rawHops);
  if (!/^\d+$/.test(rawHops) || hops < 1 || hops > MAX_HOPS) {
    throw new Error(`CLIENT_IP_TRUSTED_HOPS 1 ile ${MAX_HOPS} arasında bir tam sayı olmalı`);
  }
  return { source: rawSource as ClientIpSource, hops };
}

function isIpv4(value: string): boolean {
  const parts = value.split('.');
  return (
    parts.length === 4 &&
    parts.every((part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255)
  );
}

/** Yalnız yalın IPv4 veya IPv6 adresi kabul edilir (port, ad, boşluk ve ek içerik reddedilir). */
export function normalizeIp(raw: string | null | undefined): string | null {
  const value = raw?.trim();
  if (!value || value.length > 45) return null;
  if (isIpv4(value)) return value;
  if (!value.includes(':') || !/^[0-9a-fA-F:.]+$/.test(value)) return null;
  try {
    // URL ayrıştırıcısı IPv6 sözdizimini doğrular; kanonik küçük harfli biçimi döndürür.
    const host = new URL(`http://[${value}]/`).hostname;
    return host.slice(1, -1);
  } catch {
    return null;
  }
}

/** Seçilen tek kaynaktan doğrulanmış istemci IP'si; belirlenemezse null. */
export function resolveClientIp(headers: Headers, config: ClientIpConfig): string | null {
  switch (config.source) {
    case 'none':
      return null;
    case 'cf-connecting-ip':
      return normalizeIp(headers.get('cf-connecting-ip'));
    case 'x-forwarded-for': {
      const entries = (headers.get(FORWARDED_FOR_HEADER) ?? '').split(',');
      // Sağdan CLIENT_IP_TRUSTED_HOPS. girdi: güvenilir vekilin kendi gördüğü bağlantı adresi.
      const index = entries.length - config.hops;
      if (index < 0) return null;
      return normalizeIp(entries[index]);
    }
  }
}

/**
 * API'ye gidecek istek başlıklarını üretir: istemcinin yazdığı tüm IP başlıkları silinir ve
 * (belirlenebildiyse) doğrulanmış IP tek bir X-Forwarded-For değeri olarak yazılır.
 */
export function sanitizeClientIpHeaders(headers: Headers, config: ClientIpConfig): Headers {
  const ip = resolveClientIp(headers, config);
  const clean = new Headers(headers);
  for (const name of CLIENT_IP_HEADERS) clean.delete(name);
  if (ip) clean.set(FORWARDED_FOR_HEADER, ip);
  return clean;
}
