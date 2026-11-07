import { headers } from 'next/headers';

import { JsonLd } from '@/components/brand/json-ld';

/** Sayfa düzeyinde birden çok JSON-LD bloğu yazar; CSP nonce'u istek başlığından alınır. */
export async function PageJsonLd({ blocks }: { blocks: readonly Record<string, unknown>[] }) {
  const nonce = (await headers()).get('x-nonce') ?? undefined;
  return (
    <>
      {blocks.map((data, index) => (
        <JsonLd key={`${String(data['@type'])}-${index}`} data={data} nonce={nonce} />
      ))}
    </>
  );
}
