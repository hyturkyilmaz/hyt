// Giriş akışı sayfalarında `?sonra=<yol>` içinde tek kullanımlık token taşıyan bağlantılar olabilir
// (ör. /giris?sonra=/e-posta-dogrula?token=...). Token adres çubuğunda ve tarayıcı geçmişinde kalmasın diye
// okunduktan sonra `sonra` parametresi adresten silinir; hedef bileşen durumunda (props) zaten tutulur.

/** `sonra` değeri sorgu dizesinde `token` parametresi taşıyor mu? */
export function nextCarriesToken(next: string | null): boolean {
  if (!next) return false;
  const queryStart = next.indexOf('?');
  if (queryStart === -1) return false;
  return new URLSearchParams(next.slice(queryStart + 1)).has('token');
}

/** Adres çubuğundaki `sonra` token taşıyorsa onu siler (history.replaceState); başka parametreler kalır. */
export function stripTokenCarryingNext(): void {
  const url = new URL(window.location.href);
  if (!nextCarriesToken(url.searchParams.get('sonra'))) return;
  url.searchParams.delete('sonra');
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}`);
}
