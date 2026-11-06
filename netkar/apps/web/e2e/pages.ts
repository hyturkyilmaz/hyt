// Sınanan sayfalar: yol, ekran görüntüsü adı, beklenen h1
export const PUBLIC_PAGES = [
  { path: '/', name: 'anasayfa', h1: /Cironuzu değil, cebinize kalanı gösterir/ },
  { path: '/giris', name: 'giris', h1: /Giriş yapın/ },
  { path: '/kayit', name: 'kayit', h1: /Hesap oluşturun/ },
  { path: '/iki-adim', name: 'iki-adim', h1: /İki adımlı doğrulama/ },
  { path: '/sifre-sifirla', name: 'sifre-sifirla', h1: /Parolanızı sıfırlayın/ },
  { path: '/kullanim-kosullari', name: 'kullanim-kosullari', h1: /^Kullanım koşulları$/ },
  { path: '/kvkk-aydinlatma-metni', name: 'kvkk-aydinlatma-metni', h1: /^KVKK aydınlatma metni$/ },
] as const;

export const PANEL_PAGES = [
  { path: '/panel', name: 'panel-ozet', h1: /^Özet$/ },
  { path: '/panel/urunler', name: 'panel-urunler', h1: /^Ürünler$/ },
  { path: '/panel/siparisler', name: 'panel-siparisler', h1: /^Siparişler$/ },
  { path: '/panel/uyarilar', name: 'panel-uyarilar', h1: /^Uyarılar$/ },
  { path: '/panel/ayarlar', name: 'panel-ayarlar', h1: /^Ayarlar$/ },
] as const;

export const ALL_PAGES = [...PUBLIC_PAGES, ...PANEL_PAGES];
