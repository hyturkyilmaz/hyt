import { WaitlistForm } from './waitlist-form';

/** Sayfa altı bekleme listesi bölümü. Bağlantı kimliği: #bekleme-listesi */
export function WaitlistSection({
  title = 'Açıldığında ilk siz haber alın',
  lead = 'Ürün kapalı beta aşamasında. E-postanızı bırakın, açılışa hazır olduğumuzda size haber verelim.',
}: {
  title?: string;
  lead?: string;
}) {
  return (
    <section
      id="bekleme-listesi"
      aria-labelledby="bekleme-baslik"
      className="scroll-mt-6 border-t border-border bg-surface"
    >
      <div className="mx-auto grid max-w-content gap-8 px-gutter py-12 lg:grid-cols-2 lg:gap-16 lg:px-8 lg:py-16">
        <div>
          <h2 id="bekleme-baslik" className="text-2xl font-bold sm:text-3xl">
            {title}
          </h2>
          <p className="mt-3 max-w-xl text-base text-muted-foreground">{lead}</p>
        </div>
        <WaitlistForm />
      </div>
    </section>
  );
}
