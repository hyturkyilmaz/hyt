import { serializeJsonLd } from '@/lib/json-ld';

// Yapılandırılmış veri betiği. İçerik yalnız koddaki sabitlerden gelir ve serializeJsonLd ile
// kaçışlanır; kullanıcı girdisi buraya verilmez.
export function JsonLd({ data, nonce }: { data: Record<string, unknown>; nonce?: string }) {
  return (
    <script
      type="application/ld+json"
      nonce={nonce}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: serializeJsonLd(data) }}
    />
  );
}
