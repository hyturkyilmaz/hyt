const MONTHS = [
  'Ocak',
  'Şubat',
  'Mart',
  'Nisan',
  'Mayıs',
  'Haziran',
  'Temmuz',
  'Ağustos',
  'Eylül',
  'Ekim',
  'Kasım',
  'Aralık',
] as const;

/** "2026-11-07" -> "7 Kasım 2026" (saat dilimi ve Intl bağımsız) */
export function formatDateTr(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) throw new RangeError(`Geçersiz tarih: ${isoDate}`);
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) throw new RangeError(`Geçersiz ay: ${isoDate}`);
  return `${Number(match[3])} ${month} ${match[1]}`;
}
