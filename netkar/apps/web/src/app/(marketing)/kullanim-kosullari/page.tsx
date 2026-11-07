import type { Metadata } from 'next';

import { LegalSkeleton, type LegalSection } from '@/components/legal/draft-notice';

export const metadata: Metadata = {
  title: 'Kullanım koşulları (taslak)',
  // Taslak içerik arama motorlarına açılmaz.
  robots: { index: false, follow: false },
};

// Bölüm başlıkları docs/research/03_hukuk_ve_uyum.md §5 "Kullanım koşullarında olması gerekenler"
// kontrol listesinden alınmıştır. Bölüm metinleri ve yükümlülükler avukat incelemesinden sonra yazılır.
const SECTIONS: readonly LegalSection[] = [
  { title: 'Hizmetin tanımı (tahmini ve kesinleşmiş kâr ayrımı dahil)' },
  { title: 'Hesaplama sonuçları ve sorumluluk reddi' },
  { title: 'Üçüncü taraf hizmetlere bağımlılık (Trendyol)' },
  { title: 'Sorumluluk sınırı' },
  { title: 'Satıcının yükümlülükleri' },
  { title: 'Ücret ve faturalama' },
  { title: 'Fiyat ve koşul değişiklikleri' },
  { title: 'Fesih, veri dışa aktarımı ve silme' },
  { title: 'Fikrî mülkiyet' },
  { title: 'Gizlilik politikası ve veri işleme ekine atıf' },
  { title: 'Uygulanacak hukuk ve yetkili mahkeme' },
  { title: 'Mücbir sebep' },
];

export default function TermsPage() {
  return (
    <LegalSkeleton
      title="Kullanım koşulları"
      intro="Hizmeti kullanmadan önce geçerli olacak koşulların bölüm başlıkları."
      sections={SECTIONS}
    />
  );
}
