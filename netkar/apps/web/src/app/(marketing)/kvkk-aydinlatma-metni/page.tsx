import type { Metadata } from 'next';

import { LegalSkeleton, type LegalSection } from '@/components/legal/draft-notice';

export const metadata: Metadata = {
  title: 'KVKK aydınlatma metni (taslak)',
  robots: { index: false, follow: false },
};

// Bölüm başlıkları docs/research/03_hukuk_ve_uyum.md §2.6 (KVKK m.10 aydınlatma içeriği) ile
// §2.1, §2.4, §2.7, §2.8 konularından alınmıştır. Metinler avukat incelemesinden sonra yazılır.
const SECTIONS: readonly LegalSection[] = [
  { title: 'Veri sorumlusunun kimliği' },
  { title: 'Hangi kişisel veriler işlenir' },
  { title: 'Kişisel verilerin işlenme amaçları' },
  { title: 'Kişisel verilerin toplanma yöntemi ve hukuki sebebi' },
  { title: 'Kişisel verilerin aktarıldığı taraflar ve aktarım amacı' },
  { title: 'Yurt dışına aktarım' },
  { title: 'Saklama ve imha' },
  { title: 'Veri güvenliği ve ihlal bildirimi' },
  { title: 'Çerezler' },
  { title: 'İlgili kişi olarak haklarınız ve başvuru yöntemi (KVKK m.11)' },
];

export default function PrivacyNoticePage() {
  return (
    <LegalSkeleton
      title="KVKK aydınlatma metni"
      intro="6698 sayılı Kanun'un 10. maddesi kapsamındaki aydınlatma metninin bölüm başlıkları."
      sections={SECTIONS}
    />
  );
}
