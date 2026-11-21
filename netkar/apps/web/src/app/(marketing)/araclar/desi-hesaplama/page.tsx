import type { Metadata } from 'next';

import { Section, ToolPage, WorkedExample } from '@/components/marketing/tool-page';
import { DesiCalculator } from '@/components/tools/desi-calculator';
import { calculateDesi } from '@/lib/calc/desi';
import { formatScaled } from '@/lib/calc/money';
import { pageMetadata } from '@/lib/seo/metadata';

export const metadata: Metadata = pageMetadata('desiTool');

export default function DesiToolPage() {
  const r = calculateDesi({
    length: 300n,
    width: 200n,
    height: 100n,
    weightGrams: 1000n,
    divisor: 'domestic',
  });
  return (
    <ToolPage
      pageKey="desiTool"
      title="Desi hesaplama ve ücretlendirmeye esas değer"
      lead="Yurt içi kargoda desi, en × boy × yükseklik (cm) değerinin 3.000’e bölünmesiyle bulunur; yurt dışında bölen genellikle 5.000’dir. Kargo firması, hesaplanan desi ile gerçek ağırlıktan büyük olanı esas alır. Ölçüleri girin, hangisinin geçerli olduğunu görün."
      tool={<DesiCalculator />}
      related={['commissionTool', 'profitTool']}
    >
      <Section id="formul" title="Formül">
        <p className="rounded-md border border-border bg-surface-muted p-4 font-medium text-foreground">
          Desi = en (cm) × boy (cm) × yükseklik (cm) ÷ bölen
        </p>
        <ul className="flex list-disc flex-col gap-1.5 pl-6">
          <li>Bölen yurt içi için 3.000, yurt dışı için genellikle 5.000’dir.</li>
          <li>Ücretlendirmeye esas değer = desi ile gerçek ağırlığın (kg) büyüğü.</li>
          <li>
            Tarifeler tam desi basamaklarıyla yazıldığı için ücretlendirmeye esas değer yukarı
            yuvarlanarak da gösterilir. Firmanızın yuvarlama kuralını kendi sözleşmenizden teyit
            edin.
          </li>
        </ul>
      </Section>

      <Section id="ornek" title="Örnek hesap">
        <p>30 × 20 × 10 cm ölçülerinde, 1 kg ağırlığında bir koli (yurt içi, bölen 3.000).</p>
        <WorkedExample
          steps={[
            { label: 'Hacim: 30 × 20 × 10', value: '6.000 cm³' },
            {
              label: 'Hacimsel desi: 6.000 ÷ 3.000',
              value: formatScaled(r.volumetricHundredths, 2),
            },
            { label: 'Gerçek ağırlık (kg)', value: formatScaled(r.weightHundredths, 2) },
            {
              label: 'Ücretlendirmeye esas değer (büyük olan)',
              value: formatScaled(r.billableHundredths, 2),
            },
          ]}
        />
      </Section>

      <Section id="kargo-maliyeti" title="Kargo maliyeti neden yok?">
        <p>
          Trendyol anlaşmalı kargo tarifelerini doğrulayabildiğimiz bir kaynaktan alamadığımız için
          bu araç tutar göstermez; eski veya yanlış bir tarife göstermektense boş bırakmayı seçtik.
          Tarifenizdeki tutarı komisyon veya kâr hesaplayıcısındaki kargo alanına yazabilirsiniz.
        </p>
      </Section>
    </ToolPage>
  );
}
