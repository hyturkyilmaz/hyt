import { ApiError, NetworkError } from '@/lib/api/client';

/** 422 `cursor_invalid`: imleç bu sorguya ait değil ya da bozuk; liste baştan yüklenir (denetim kuralı 11). */
export function isCursorInvalid(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 422 &&
    (error.errors ?? []).some((e) => e.field === 'cursor' && e.code === 'cursor_invalid')
  );
}

/** Rapor hatasını kullanıcıya sade Türkçe cümle olarak anlatır; sunucu ayrıntısı taşınmaz. */
export function describeReportError(error: unknown): string {
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.';
  }
  if (error instanceof ApiError) {
    if (error.status === 429 || error.status === 503) {
      return 'Rapor şu an yoğun. Birkaç saniye sonra tekrar deneyin.';
    }
    if (error.status === 404) {
      return 'İstenen kayıt bulunamadı.';
    }
    if (error.status === 422) {
      return 'İstek geçerli değil. Sayfayı yenileyip tekrar deneyin.';
    }
    if (error.status >= 500) {
      return 'Rapor şu an hazırlanamadı. Biraz sonra tekrar deneyin.';
    }
  }
  return 'Rapor yüklenemedi. Tekrar deneyin.';
}
