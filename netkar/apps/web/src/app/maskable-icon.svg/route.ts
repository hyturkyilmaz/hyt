import { buildBrandIconSvg, svgResponse } from '@/lib/brand-icon';

export function GET() {
  return svgResponse(buildBrandIconSvg({ maskable: true }));
}
