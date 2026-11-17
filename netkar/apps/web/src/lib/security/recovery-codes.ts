// Kurtarma kodlarının istemci tarafı yardımcıları. Kodlar yalnız bellekte tutulur: storage, çerez, günlük yok.

/** İndirilen dosyanın metni: kimlik ya da adres içermez, yalnız kodlar ve kullanım notu. */
export function formatRecoveryCodesFile(codes: readonly string[], now: Date = new Date()): string {
  const date = now.toISOString().slice(0, 10);
  return [
    'NetKâr kurtarma kodları',
    `Oluşturulma: ${date}`,
    '',
    'Her kod yalnız BİR kez kullanılabilir. Doğrulama uygulamanıza erişemediğinizde girişte kod yerine yazın.',
    'Bu dosyayı güvenli bir yerde saklayın; başkasıyla paylaşmayın.',
    '',
    ...codes.map((code, index) => `${String(index + 1).padStart(2, '0')}. ${code}`),
    '',
  ].join('\n');
}

/** Metni .txt olarak indirir (tarayıcıda, ağ isteği yok). Nesne adresi hemen serbest bırakılır. */
export function downloadTextFile(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  try {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
