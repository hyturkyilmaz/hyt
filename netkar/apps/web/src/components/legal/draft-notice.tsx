import { TriangleAlert } from 'lucide-react';
import type { ReactNode } from 'react';

/** Yasal sayfalarda en üstte görünen taslak uyarısı. İçerik hukuki inceleme sonrası eklenir. */
export function DraftNotice() {
  return (
    <aside
      aria-label="Taslak uyarısı"
      className="flex items-start gap-3 rounded-md border border-border bg-warning-soft p-4 text-base"
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <p>
        <strong className="font-semibold">Taslak, hukuki inceleme bekliyor.</strong> Bu sayfa yalnız
        bölüm iskeletidir; bağlayıcı bir metin değildir. Bölümlerin içeriği, bir avukat tarafından
        incelendikten sonra eklenecektir.
      </p>
    </aside>
  );
}

export interface LegalSection {
  title: string;
}

/** Numaralı bölüm iskeleti: her bölümde "metin eklenecek" yer tutucusu bulunur. */
export function LegalSkeleton({
  title,
  intro,
  sections,
  footer,
}: {
  title: string;
  intro: string;
  sections: readonly LegalSection[];
  footer?: ReactNode;
}) {
  return (
    <article className="mx-auto flex max-w-3xl flex-col gap-6 px-gutter py-10 lg:px-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold">{title}</h1>
        <p className="text-base text-muted-foreground">{intro}</p>
      </header>
      <DraftNotice />
      <ol className="flex flex-col gap-5">
        {sections.map((section, index) => (
          <li key={section.title}>
            <section aria-labelledby={`bolum-${index + 1}`} className="flex flex-col gap-1">
              <h2 id={`bolum-${index + 1}`} className="text-xl font-semibold">
                {index + 1}. {section.title}
              </h2>
              <p className="text-base text-muted-foreground">
                Bu bölümün metni hukuki inceleme sonrası eklenecek.
              </p>
            </section>
          </li>
        ))}
      </ol>
      {footer}
    </article>
  );
}
