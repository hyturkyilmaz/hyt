// Saniye cinsinden bekleme süresini doğal Türkçe ifadeye çevirir (ör. "yaklaşık 12 saat sonra", "yarın").
// Başlık ayrıştırması `client.ts` içindedir; burada yalnız metin üretilir.

const MINUTE = 60;
const HOUR = 3600;
const DAY = 24 * HOUR;

/**
 * Bekleme süresi ifadesi, "tekrar deneyin" cümlesinin başına gelecek biçimde:
 * 60 sn altı "birkaç saniye sonra", dakika ölçeği "yaklaşık N dakika sonra", 24 saate kadar "yaklaşık N saat sonra",
 * daha uzunsa "yaklaşık N gün sonra". Sayılar yukarı yuvarlanır: kullanıcı söylenen süre dolunca yine sınıra
 * takılmasın. Süre geçersizse (negatif, sonsuz, sayı değil) null döner.
 */
export function describeWait(seconds: number | undefined): string | null {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < MINUTE) return 'birkaç saniye sonra';
  const minutes = Math.ceil(seconds / MINUTE);
  // 60 dakikaya ulaşan değer saat ölçeğine geçer ("yaklaşık 60 dakika" denmez)
  if (minutes < 60) return `yaklaşık ${minutes} dakika sonra`;
  if (seconds <= DAY) return `yaklaşık ${Math.ceil(seconds / HOUR)} saat sonra`;
  return `yaklaşık ${Math.ceil(seconds / DAY)} gün sonra`;
}

/** "Çok fazla deneme yaptınız. <süre> tekrar deneyin." cümlesi; süre bilinmiyorsa null (çağıran genel mesajı kullanır). */
export function describeRateLimitWait(seconds: number | undefined): string | null {
  const wait = describeWait(seconds);
  if (!wait) return null;
  const sentence = wait.charAt(0).toLocaleUpperCase('tr-TR') + wait.slice(1);
  return `Çok fazla deneme yaptınız. ${sentence} tekrar deneyin.`;
}
