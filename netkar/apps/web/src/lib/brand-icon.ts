import { brand } from '@/config/brand';

// Marka adı yapılandırmadan gelir; yine de XML için kaçışlanır.
function escapeXml(value: string): string {
  const map: Record<string, string> = {
    '<': '&lt;',
    '>': '&gt;',
    '&': '&amp;',
    '"': '&quot;',
    "'": '&apos;',
  };
  return value.replace(/[<>&"']/g, (char) => map[char] ?? char);
}

// Geçici ikon: marka adının baş harfi. `maskable` sürümde harf güvenli alana (orta %60) sığar.
export function buildBrandIconSvg({ maskable }: { maskable: boolean }): string {
  const radius = maskable ? 0 : 112;
  const fontSize = maskable ? 280 : 340;
  const letter = escapeXml(brand.initial);
  const label = escapeXml(brand.name);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="${label}">
<rect width="512" height="512" rx="${radius}" fill="#23409a"/>
<text x="256" y="256" text-anchor="middle" dominant-baseline="central" font-family="Inter, system-ui, sans-serif" font-weight="700" font-size="${fontSize}" fill="#ffffff">${letter}</text>
</svg>`;
}

export function svgResponse(svg: string): Response {
  return new Response(svg, {
    headers: {
      'Content-Type': 'image/svg+xml; charset=utf-8',
      'Cache-Control': 'public, max-age=86400',
      // SVG içinde betik çalışmasın
      'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'",
    },
  });
}
