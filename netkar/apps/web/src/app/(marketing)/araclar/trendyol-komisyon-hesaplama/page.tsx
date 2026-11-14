import type { Metadata } from 'next';
import Link from 'next/link';

import { CommissionCalculator } from '@/components/tools/commission-calculator';
import { Section, ToolPage, WorkedExample } from '@/components/marketing/tool-page';
import { Callout } from '@/components/tools/fields';
import { calculateCommission } from '@/lib/calc/commission';
import { formatBps, formatKurus } from '@/lib/calc/money';
import { pageMetadata } from '@/lib/seo/metadata';

export const metadata: Metadata = pageMetadata('commissionTool');

// Örnek hesap, hesaplayıcıyla aynı fonksiyonlarla sunucuda üretilir (arama motoruna görünür).
const EXAMPLE = {
  priceIncl: 60000n,
  vatRatePct: 20,
  commissionBps: 2100n,
  commissionIncludesVat: true,
  shipping: 0n,
  shippingIncludesVat: false,
  serviceFeeExcl: 0n,
} as const;

export default function CommissionToolPage() {
  const r = calculateCommission(EXAMPLE);
  const alt = calculateCommission({ ...EXAMPLE, commissionIncludesVat: false });
  const gap = formatKurus(r.expectedPayout - alt.expectedPayout);
  return (
    <ToolPage
      pageKey="commissionTool"
      title="Trendyol komisyon hesaplama (2026)"
      lead="Trendyol komisyonu, satış tutarınıza (KDV dahil, satıcı indirimi düşülmüş) kategorinize göre değişen bir oranla uygulanır. Bizim varsayımımıza göre bu tutarın içinde %20 KDV bulunur. Bunun üzerine %1 e-ticaret stopajı ve varsa kargo ile platform hizmet bedeli eklenince hesabınıza geçecek tutar çıkar."
      tool={<CommissionCalculator />}
      related={['profitTool', 'desiTool']}
    >
      <Section id="varsayim" title="Teyit bekleyen varsayım: komisyonun KDV’si">
        <Callout title="Varsayım" tone="warning">
          <p>
            Komisyon oranı KDV dahil satış tutarına uygulanır ve hesaplayıcı varsayılan olarak
            komisyon tutarının KDV içerdiğini kabul eder: komisyonun %20 KDV’si, bu tutarın içinden
            ayrılır.
          </p>
          <p>
            Kaynaklar arasında bu konuda çelişki var; bazı rehberler KDV’yi komisyonun üstüne
            ekliyor. Gerçek komisyon faturasıyla doğrulama aşamasındayız. Hesaplayıcıdaki “Komisyon
            tutarı” seçeneğiyle iki varsayımı karşılaştırabilirsiniz: 600 TL’lik örnekte iki
            varsayım arasındaki fark satış başına {gap} olur.
          </p>
        </Callout>
      </Section>

      <Section id="formul" title="Nasıl hesaplıyoruz?">
        <ul className="flex list-disc flex-col gap-1.5 pl-6">
          <li>KDV hariç satış = KDV dahil satış ÷ (1 + KDV oranı).</li>
          <li>Komisyon (KDV dahil) = KDV dahil satış × komisyon oranı.</li>
          <li>
            Komisyon (KDV hariç) = komisyon (KDV dahil) ÷ 1,20; komisyonun KDV’si aradaki fark.
          </li>
          <li>Hakediş = KDV dahil satış − komisyon (KDV dahil).</li>
          <li>Stopaj = KDV hariç satış × %1. Gider değil, peşin kesilen vergidir.</li>
          <li>
            Hesabınıza geçecek tutar = hakediş − kargo ve hizmet bedeli faturaları (KDV dahil) −
            stopaj.
          </li>
        </ul>
        <p>
          Her kalem kuruşa bir kez yuvarlanır (yarım kuruş yukarı). Hesaplamalar tamsayı kuruşla
          yapılır, ondalıklı sayı kullanılmaz. Kurallar{' '}
          <Link href="/ozellikler" className="text-primary underline underline-offset-4">
            uygulamadaki kâr motoruyla
          </Link>{' '}
          aynıdır.
        </p>
      </Section>

      <Section id="ornek" title="Örnek hesap">
        <p>
          600 TL’ye satılan, %20 KDV’li bir ürün; komisyon oranı %21 (örnek bir değerdir, sizin
          kategorinizin oranını panelinizden kontrol edin).
        </p>
        <WorkedExample
          steps={[
            { label: 'KDV hariç satış: 600,00 ÷ 1,20', value: formatKurus(r.price.excl) },
            {
              label: `Komisyon (KDV dahil): 600,00 × ${formatBps(EXAMPLE.commissionBps, 0)}`,
              value: formatKurus(r.commissionIncl),
            },
            { label: 'Komisyon (KDV hariç): 126,00 ÷ 1,20', value: formatKurus(r.commissionExcl) },
            { label: 'Komisyonun KDV’si', value: formatKurus(r.commissionVat) },
            { label: 'Hakediş: 600,00 − 126,00', value: formatKurus(r.settlement) },
            { label: 'Stopaj: 500,00 × %1', value: formatKurus(r.withholding) },
            {
              label: 'Hesabınıza geçecek tutar (kargo olmadan)',
              value: formatKurus(r.expectedPayout),
            },
          ]}
        />
      </Section>

      <Section id="sss" title="Kısa sorular">
        <div>
          <h3 className="text-lg font-semibold text-foreground">
            Trendyol karşılamalı kupon komisyonu düşürür mü?
          </h3>
          <p className="mt-1">
            Varsayımımıza göre hayır: komisyon matrahı, satıcının satış tutarıdır ve Trendyol’un
            karşıladığı indirim bu tutardan düşülmez. Satıcı indirimi ise matrahı düşürür. Bu
            noktayı da gerçek ekstre verisiyle doğruluyoruz.
          </p>
        </div>
        <div>
          <h3 className="text-lg font-semibold text-foreground">
            İade olunca komisyon geri gelir mi?
          </h3>
          <p className="mt-1">
            Ekstrede iade satırında komisyon ters yazılır; bu yüzden iade edilen tutarın komisyonu
            geri verilir. Hizmet bedelinin iadede geri verilip verilmediği ise henüz teyit
            beklemektedir.
          </p>
        </div>
        <div>
          <h3 className="text-lg font-semibold text-foreground">
            Komisyon oranını nereden bulurum?
          </h3>
          <p className="mt-1">
            Trendyol satıcı panelinizde, kategorinizin komisyon tablosunda. Oranlar kategoriye ve
            zamana göre değiştiği için bu sayfada hazır bir oran listesi yayımlamıyoruz.
          </p>
        </div>
      </Section>
    </ToolPage>
  );
}
