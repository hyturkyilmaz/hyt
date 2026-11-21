import qrcode from 'qrcode-generator';

/**
 * QR kodu İSTEMCİDE üretilir (qrcode-generator, MIT, sıfır bağımlılık): sır hiçbir dış servise gitmez.
 * Çıktı React ile çizilen tek bir SVG yoludur (innerHTML yok). Okuyucuların güvenilirliği için zemin her temada
 * beyaz, sessiz bölge 4 modüldür.
 */
const QUIET_ZONE = 4;

export function buildQrPath(value: string): { size: number; path: string } {
  const qr = qrcode(0, 'M');
  qr.addData(value);
  qr.make();
  const count = qr.getModuleCount();
  const parts: string[] = [];
  for (let row = 0; row < count; row += 1) {
    for (let col = 0; col < count; col += 1) {
      if (qr.isDark(row, col)) parts.push(`M${col + QUIET_ZONE} ${row + QUIET_ZONE}h1v1h-1z`);
    }
  }
  return { size: count + QUIET_ZONE * 2, path: parts.join('') };
}

export function QrCode({ value, label }: { value: string; label: string }) {
  const { size, path } = buildQrPath(value);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      shapeRendering="crispEdges"
      className="size-48 max-w-full rounded-md border border-border bg-white"
    >
      <rect width={size} height={size} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  );
}
