// Sık sorulan sorular. Her cevap ilk cümlede doğrudan yanıt verir. Kaynak: docs/12_kar_motoru.md,
// docs/50_guvenlik.md, docs/adr/0003 ve 0004, docs/research/05 itiraz tablosu.
// Ürün kapalı betadadır: henüz yapılmayan şeyler "planlanıyor" diye yazılır.

export interface FaqEntry {
  id: string;
  question: string;
  answer: string;
}

export interface FaqCategory {
  id: string;
  title: string;
  items: readonly FaqEntry[];
}

export const FAQ_CATEGORIES: readonly FaqCategory[] = [
  {
    id: 'kurulum',
    title: 'Kurulum',
    items: [
      {
        id: 'acik-mi',
        question: 'Uygulama şu anda kullanıma açık mı?',
        answer:
          'Hayır, henüz kapalı beta aşamasındadır. Bekleme listesine katılırsanız açılışta size haber veririz. Ücretsiz hesaplayıcılar bugün kullanılabilir ve kayıt istemez.',
      },
      {
        id: 'pazaryeri',
        question: 'Hangi pazaryerlerini destekliyor?',
        answer:
          'İlk sürüm yalnızca Trendyol içindir. Hepsiburada gibi diğer pazaryerleri için henüz tarih vermiyoruz; verdiğimiz tarihi tutamayacaksak vermemeyi tercih ediyoruz.',
      },
      {
        id: 'gerekenler',
        question: 'Bağlanmak için ne gerekir?',
        answer:
          'Trendyol satıcı panelinizden alacağınız API bilgileri gerekir: satıcı kimliği, API anahtarı ve API sırrı. Ürün maliyetlerini ayrıca siz girersiniz, çünkü Trendyol bu bilgiyi tutmaz.',
      },
    ],
  },
  {
    id: 'veri-ve-guvenlik',
    title: 'Veri ve güvenlik',
    items: [
      {
        id: 'api-guvenli-mi',
        question: 'API bilgilerim güvende mi?',
        answer:
          'API anahtarınız veritabanında düz metin olarak durmaz: zarf şifrelemeyle (AES-256-GCM) saklanır ve ekranda tamamı gösterilmez. Hangi kontrollerin uygulandığını, hangilerinin henüz tamamlanmadığını güvenlik sayfasında yazdık.',
      },
      {
        id: 'degisiklik-yapar-mi',
        question: 'Ürünlerimde veya fiyatlarımda değişiklik yapar mı?',
        answer:
          'Hayır. Trendyol’a yalnızca okuma isteği göndeririz; ürün, fiyat veya stok değiştirmeyiz.',
      },
      {
        id: 'musteri-verisi',
        question: 'Müşterilerimin bilgileri saklanıyor mu?',
        answer:
          'Hayır. Müşterinin adı, adresi, telefonu ve e-postası kaydedilmez. Kâr hesabı bunlara ihtiyaç duymaz; siparişten yalnız tutarları, ürünü ve ilini alırız.',
      },
      {
        id: 'baglanti-kesme',
        question: 'Bağlantıyı nasıl keserim?',
        answer:
          'En kesin yol, Trendyol panelinden API anahtarınızı yenilemektir: eski anahtar o anda çalışmaz. Uygulama içinden bağlantıyı kaldırma ekranı da açılıştan önce hazır olacak.',
      },
    ],
  },
  {
    id: 'hesaplama-yontemi',
    title: 'Hesaplama yöntemi',
    items: [
      {
        id: 'net-kar-formulu',
        question: 'Net kâr nasıl hesaplanıyor?',
        answer:
          'Net kâr, KDV hariç net satıştan ürün maliyeti, komisyon, gönderi ve iade kargosu, platform hizmet bedeli ve reklam düşülerek bulunur. KDV ve stopaj kâra girmez; ayrı satırlarda gösterilir.',
      },
      {
        id: 'stopaj',
        question: 'Stopaj neden kâra girmiyor?',
        answer:
          'Stopaj gider değil, sizin adınıza peşin kesilen vergidir ve beyanda mahsup edilir. Bu yüzden onu nakit akışı satırında gösteriyoruz. Kendi durumunuz için mali müşavirinize danışın.',
      },
      {
        id: 'tahmin-kesin',
        question: 'Rakamlar tahmin mi, kesin mi?',
        answer:
          'Sipariş geldiği anda tahmindir; Trendyol hakediş ekstresi geldikçe kalem kalem kesinleşir. Her rakamın yanında kaynağı yazar: Trendyol ekstresi mi, sizin girdiğiniz maliyet mi, tahmin mi.',
      },
      {
        id: 'komisyon-kdv',
        question: 'Komisyonun KDV’si nasıl işleniyor?',
        answer:
          'Komisyon oranı KDV dahil satış tutarına uygulanır ve şu anki varsayımımız, komisyon tutarının içinde %20 KDV bulunduğudur. Bu noktayı gerçek komisyon faturalarıyla doğruluyoruz; farklı çıkarsa hesap güncellenir ve açıkça duyurulur.',
      },
      {
        id: 'reklam',
        question: 'Reklam harcaması nasıl alınıyor?',
        answer:
          'Reklam harcaması için şu an kullanabildiğimiz bir Trendyol API’si yok; panelden indirdiğiniz reklam raporunu yüklersiniz. Ürünle eşleşen harcama o ürüne yazılır, eşleşmeyen satışlara oranla dağıtılır ve “tahmini” diye işaretlenir.',
      },
      {
        id: 'maliyet-eksik',
        question: 'Ürün maliyetini girmezsem ne olur?',
        answer:
          'Maliyeti olmayan ürün için net kâr hesaplanmaz; sıfır maliyet varsaymayız. Onun yerine maliyetten önceki katkıyı gösterir ve ürünü “maliyet eksik” diye işaretleriz.',
      },
      {
        id: 'hesaplayici-ucretsiz',
        question: 'Hesaplayıcılar ücretsiz mi, girdiğim rakamlar nereye gidiyor?',
        answer:
          'Evet, ücretsizdir ve kayıt istemez. Girdiğiniz rakamlar tarayıcınızda hesaplanır, sunucuya gönderilmez.',
      },
    ],
  },
  {
    id: 'fiyat-ve-fatura',
    title: 'Fiyat ve fatura',
    items: [
      {
        id: 'fiyat',
        question: 'Fiyatı ne kadar?',
        answer:
          'Lansman fiyatı henüz kesinleşmedi. Açıklandığında bekleme listesindekilere önce haber vereceğiz ve fiyatların KDV durumunu açıkça yazacağız.',
      },
    ],
  },
  {
    id: 'muhasebeci-ve-ajans',
    title: 'Muhasebeci ve ajans',
    items: [
      {
        id: 'entegrator',
        question: 'Entegratörümle birlikte kullanılır mı?',
        answer:
          'Evet, onun yerine geçmeyi hedeflemiyoruz. Sipariş, stok ve fatura akışı entegratörde kalır; biz kârı, hakediş eşleşmesini ve reklamı ürün bazında ekleriz. Aynı API bilgilerinin iki yerde kullanılıp kullanılamayacağını Trendyol kurallarına göre doğruluyoruz.',
      },
      {
        id: 'muhasebeci',
        question: 'Muhasebecim veya ajansım kullanabilir mi?',
        answer:
          'Muhasebeci ve ajans erişimi planlanıyor, ancak kapsamı ve fiyatı henüz kesinleşmedi. İlginizi bekleme listesi formuyla iletebilirsiniz.',
      },
    ],
  },
  {
    id: 'mobil-ve-yapay-zeka',
    title: 'Mobil uygulama ve müşteri soruları',
    items: [
      {
        id: 'mobil',
        question: 'Mobil uygulama var mı?',
        answer:
          'Henüz yok. Web arayüzü telefonda rahat kullanılacak biçimde tasarlanıyor; mobil uygulama ve bildirimler planlanıyor ama tarih vermiyoruz.',
      },
      {
        id: 'musteri-sorulari',
        question: 'Müşteri sorularına yanıt taslağı hazırlanacak mı?',
        answer:
          'Planlanıyor. Yalnızca taslak hazırlanır; siz okuyup onaylamadan hiçbir yanıt gönderilmez.',
      },
    ],
  },
];

/** Ana sayfadaki kısa liste (kimlikler FAQ_CATEGORIES içindedir). */
export const HOME_FAQ_IDS = [
  'api-guvenli-mi',
  'entegrator',
  'tahmin-kesin',
  'pazaryeri',
  'hesaplayici-ucretsiz',
] as const;

export function allFaqEntries(): FaqEntry[] {
  return FAQ_CATEGORIES.flatMap((category) => [...category.items]);
}

export function homeFaqEntries(): FaqEntry[] {
  const all = allFaqEntries();
  return HOME_FAQ_IDS.map((id) => {
    const found = all.find((entry) => entry.id === id);
    if (!found) throw new Error(`SSS kaydı bulunamadı: ${id}`);
    return found;
  });
}
