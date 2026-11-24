'use client';

import { Check, Copy, Download } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { downloadTextFile, formatRecoveryCodesFile } from '@/lib/security/recovery-codes';

/**
 * Kurtarma kodlarını BİR KEZ gösterir. Kodlar yalnız bu bileşenin belleğindedir; kullanıcı "kaydettim" demeden
 * "Bitti" açılmaz, sayfadan ayrılırken tarayıcı uyarır. Sunucu düz metni bir daha vermez.
 */
export function RecoveryCodesPanel({
  codes,
  onDone,
}: {
  codes: readonly string[];
  onDone: () => void;
}) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const checkboxId = useId();

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    if (saved) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [saved]);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(codes.join('\n'));
      setCopied(true);
      toast.success('Kodlar panoya kopyalandı.');
    } catch {
      toast.error('Kopyalanamadı. Kodları elle yazın ya da dosya olarak indirin.');
    }
  }

  function onDownload() {
    downloadTextFile('netkar-kurtarma-kodlari.txt', formatRecoveryCodesFile(codes));
  }

  return (
    <section aria-labelledby={`${checkboxId}-title`} className="flex flex-col gap-4">
      <h3
        id={`${checkboxId}-title`}
        ref={headingRef}
        tabIndex={-1}
        className="text-lg font-semibold focus:outline-none"
      >
        Kurtarma kodlarınızı kaydedin
      </h3>
      <p className="text-sm text-muted-foreground">
        Doğrulama uygulamanıza erişemezseniz bu kodlardan biriyle giriş yapabilirsiniz. Her kod
        yalnız bir kez çalışır.{' '}
        <strong className="text-foreground">Bu kodlar bir daha gösterilmez.</strong>
      </p>
      <ol
        aria-label="Kurtarma kodları"
        className="grid grid-cols-1 gap-2 rounded-md border border-border bg-surface-muted p-4 sm:grid-cols-2"
      >
        {codes.map((code) => (
          <li key={code} className="num font-mono text-base tracking-wide">
            {code}
          </li>
        ))}
      </ol>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Button variant="secondary" onClick={onCopy}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? 'Kopyalandı' : 'Kopyala'}
        </Button>
        <Button variant="secondary" onClick={onDownload}>
          <Download aria-hidden="true" />
          Dosya olarak indir
        </Button>
      </div>
      <label htmlFor={checkboxId} className="flex min-h-touch items-center gap-3 text-base">
        <input
          id={checkboxId}
          type="checkbox"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
          className="size-5 shrink-0 accent-primary"
        />
        Kodları güvenli bir yere kaydettim
      </label>
      <Button onClick={onDone} disabled={!saved} aria-disabled={!saved} className="sm:self-start">
        Bitti
      </Button>
    </section>
  );
}
