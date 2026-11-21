import type { Metadata } from 'next';
import Link from 'next/link';

import { Section, ToolPage, WorkedExample } from '@/components/marketing/tool-page';
import { Callout } from '@/components/tools/fields';
import { ProfitCalculator } from '@/components/tools/profit-calculator';
import { formatBps, formatKurus } from '@/lib/calc/money';
import { calculateProfit, type ProfitInput } from '@/lib/calc/profit';
import { pageMetadata } from '@/lib/seo/metadata';

export const metadata: Metadata = pageMetadata('profitTool');

// Örnek hesap (iade payı ve reklam olmadan): hesaplayıcıyla aynı fonksiyonlarla sunucuda üretilir.
const EXAMPLE: ProfitInput = {
  priceIncl: 60000n,
  vatRatePct: 20,
  cost: 25000n,
  costIncludesVat: false,
  costVatRatePct: 20,
  commissionBps: 2100n,
  commissionIncludesVat: true,
  shipping: 6000n,
  shippingIncludesVat: false,
  returnShipping: 6000n,
  serviceFeeExcl: 0n,
  ad: { kind: 'amount', amount: 0n },
  returnRateBps: 0n,
  unsellableBps: 0n,
};

export default function ProfitToolPage() {
  const r = calculateProfit(EXAMPLE);
  return (
    <ToolPage
      pageKey="profitTool"
      title="Trendyol kâr hesaplama: reklam ve iade dahil net kâr"
      lead="Net kâr, KDV hariç satıştan ürün maliyeti, komisyon, kargo, platform hizmet bedeli, reklam ve beklenen iade payı düşülerek bulunur. KDV ve stopaj kâra girmez. İade payı için geçmiş iade oranınızı yazmanız yeterli; araç ayrıca net kârın sıfır olduğu başabaş satış fiyatını ve başabaş ROAS’ı verir."
      tool={<ProfitCalculator />}
      related={['commissionTool', 'desiTool']}
    >
      <Section id="formul" title="Formül">
        <p className="rounded-md border border-border bg-surface-muted p-4 font-medium text-foreground">
          Net kâr = net satış (KDV hariç) − ürün maliyeti − komisyon − gönderi kargo − platform
          hizmet bedeli − reklam − beklenen iade payı
        </p>
        <ul className="flex list-disc flex-col gap-1.5 pl-6">
          <li>
            Giderler KDV hariç tutarlarıyla toplanır; KDV ayrı bir bilgi satırında gösterilir.
          </li>
          <li>
            Stopaj gider değil, peşin kesilen vergidir; kâra girmez, nakit akışı satırında görünür.
          </li>
          <li>
            Beklenen iade payı = iade oranı × (iade olmasaydı kâr − iade olursa kâr). İade olursa
            satış ve komisyon geri yazılır; ürün stoğa döner (satılamayan payı hariç); gönderi
            kargo, iade kargo, hizmet bedeli ve reklam geri alınmaz.
          </li>
          <li>Net kâr marjı = net kâr ÷ net satış (KDV hariç).</li>
          <li>Başabaş ROAS = net satış (KDV hariç) ÷ reklam öncesi net kâr.</li>
        </ul>
        <p>
          Her kalem kuruşa bir kez yuvarlanır, net kâr yuvarlanmış kalemlerin farkıdır. Bu yüzden
          kalemleri ekranda topladığınızda sonucu kuruşu kuruşuna bulursunuz. Kurallar{' '}
          <Link href="/ozellikler" className="text-primary underline underline-offset-4">
            uygulamadaki kâr motoruyla
          </Link>{' '}
          aynıdır.
        </p>
      </Section>

      <Section id="varsayimlar" title="Varsayımlar">
        <Callout title="Teyit bekleyen noktalar" tone="warning">
          <ul className="flex list-disc flex-col gap-1.5 pl-6">
            <li>
              Komisyon tutarı KDV dahil kabul edilir; seçenekle alternatifine geçebilirsiniz. Gerçek
              komisyon faturasıyla doğruluyoruz.
            </li>
            <li>
              İadede platform hizmet bedelinin geri verilmediği varsayılır. Bu, iade payını artırır.
            </li>
            <li>
              Reklam girişinde ROAS seçerseniz harcama, KDV dahil satışın ROAS’a bölünmesiyle
              bulunur ve KDV hariç sayılır. Trendyol panelindeki ROAS tanımı doğrulanmadı.
            </li>
            <li>
              Kargo, iade kargosu ve alış maliyetinin KDV’si için kullandığınız seçenekleri kontrol
              edin.
            </li>
          </ul>
        </Callout>
      </Section>

      <Section id="ornek" title="Örnek hesap">
        <p>
          600 TL’ye satılan, %20 KDV’li bir ürün. Alış maliyeti 250,00 TL (KDV hariç), komisyon
          oranı %21, gönderi kargo 60,00 TL (KDV hariç). İade ve reklam yok. Rakamlar örnektir.
        </p>
        <WorkedExample
          steps={[
            { label: 'Net satış (KDV hariç): 600,00 ÷ 1,20', value: formatKurus(r.salesExcl) },
            { label: 'Ürün maliyeti', value: `-${formatKurus(r.cost)}` },
            {
              label: `Komisyon (KDV hariç): 600,00 × ${formatBps(EXAMPLE.commissionBps, 0)} ÷ 1,20`,
              value: `-${formatKurus(r.commissionExcl)}`,
            },
            { label: 'Gönderi kargo (KDV hariç)', value: `-${formatKurus(r.shipping)}` },
            { label: 'Net kâr', value: formatKurus(r.netProfit) },
            { label: 'Net kâr marjı', value: r.marginBps === null ? '-' : formatBps(r.marginBps) },
            {
              label: 'Başabaş satış fiyatı (KDV dahil)',
              value: r.breakEvenPrice === null ? '-' : formatKurus(r.breakEvenPrice),
            },
          ]}
        />
      </Section>

      <Section id="tek-urun" title="Tek ürün kolay, üç yüz ürün zor">
        <p>
          Bu araç bir ürünün olması gereken kârını gösterir. Gerçekte iade, kupon ve reklam
          kesintileri siparişe göre değişir. Uygulama bunu Trendyol hakediş ekstresinden ürün
          bazında okumak için tasarlanıyor; bekleme listesine katılarak açılıştan haberdar
          olabilirsiniz.
        </p>
      </Section>
    </ToolPage>
  );
}
