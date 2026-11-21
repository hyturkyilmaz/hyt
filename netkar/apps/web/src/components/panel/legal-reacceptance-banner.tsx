'use client';

import { FileText, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useId, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ApiError, describeApiError } from '@/lib/api/client';
import { legalApi, type LegalPending } from '@/lib/api/endpoints';
import { LEGAL_DOCS } from '@/lib/legal';

/**
 * Yeni belge sürümü yeniden kabul bandı. Kullanım koşulları ya da aydınlatma metni yeni sürüme geçince
 * kullanıcı sürümü okuyup işaretler; kabul sürüm numarasıyla sunucuya gider (sürüm güncel değilse 409).
 * `enforced` iken sunucu veri yazma uçlarını kabule kadar 403 ile kapatır; okuma ve dışa aktarma açık kalır.
 * Bekleyen sürüm yoksa hiçbir şey çizilmez. Belge METNİ burada yoktur (sayfalar avukat onayı bekler).
 */
export function LegalReacceptanceBanner({
  pending,
  enforced,
}: {
  pending: LegalPending[];
  enforced: boolean;
}) {
  const router = useRouter();
  const baseId = useId();
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  if (pending.length === 0) return null;
  const allChecked = pending.every((doc) => checked[doc.doc_type]);

  async function onAccept() {
    setBusy(true);
    try {
      await legalApi.accept(
        pending.map((doc) => ({ doc_type: doc.doc_type, version: doc.version })),
      );
      toast.success('Onayınız kaydedildi.');
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.code === 'legal-version-stale') {
        // Bu arada yeni sürüm yayınlandı: güncel sürümü okumadan kabul kaydı oluşmaz.
        toast.error('Belge sürümü güncellendi. Güncel sürümü okuyup yeniden onaylayın.');
        setChecked({});
        router.refresh();
        return;
      }
      toast.error(describeApiError(error, 'Onay kaydedilemedi. Lütfen tekrar deneyin.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby={`${baseId}-title`}
      className="flex flex-col gap-4 rounded-md border border-warning bg-warning-soft p-4 text-sm"
    >
      <div className="flex items-start gap-3">
        <FileText className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden="true" />
        <div className="flex flex-col gap-1">
          <h2 id={`${baseId}-title`} className="font-semibold">
            Güncel koşulları gözden geçirin
          </h2>
          <p>
            {enforced
              ? 'Aşağıdaki belgeler yeni bir sürüme geçti. Onaylayana dek mağaza bağlama ve veri girişi kapalıdır; verilerinizi görüntülemeye devam edebilirsiniz.'
              : 'Aşağıdaki belgeler yeni bir sürüme geçti. Lütfen gözden geçirip onaylayın.'}
          </p>
        </div>
      </div>
      <ul className="flex flex-col gap-3">
        {pending.map((doc) => {
          const meta = LEGAL_DOCS[doc.doc_type];
          const id = `${baseId}-${doc.doc_type}`;
          return (
            <li key={doc.doc_type} className="flex items-start gap-3">
              <input
                id={id}
                type="checkbox"
                checked={checked[doc.doc_type] === true}
                onChange={(event) =>
                  setChecked((prev) => ({ ...prev, [doc.doc_type]: event.target.checked }))
                }
                aria-required="true"
                className="mt-0.5 size-6 shrink-0 accent-[var(--primary)]"
              />
              <label htmlFor={id} className="leading-normal">
                <a
                  href={meta.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-primary underline underline-offset-4"
                >
                  {meta.label}
                </a>{' '}
                <span className="text-muted-foreground">
                  (yeni sekmede açılır; sürüm {doc.version})
                </span>{' '}
                {meta.confirm}.
              </label>
            </li>
          );
        })}
      </ul>
      <div>
        <Button size="sm" onClick={onAccept} disabled={!allChecked || busy}>
          {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
          Onayla
        </Button>
      </div>
    </section>
  );
}
