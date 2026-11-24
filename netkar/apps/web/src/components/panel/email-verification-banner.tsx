'use client';

import { CircleAlert, Loader2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';

/**
 * Doğrulanmamış hesap uyarı bandı. Doğrulanana dek mağaza bağlama ve veri yazma sunucuda kapalıdır
 * (403 email-not-verified); bant nedenini söyler ve doğrulama e-postasını yeniden gönderir.
 * Doğrulanmış hesapta hiçbir şey çizilmez.
 */
export function EmailVerificationBanner({ verified, email }: { verified: boolean; email: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);

  if (verified) return null;

  async function onResend() {
    setPending(true);
    try {
      await authApi.resendEmailVerification();
      setSent(true);
      toast.success('Doğrulama e-postası gönderildi.');
    } catch (error) {
      if (error instanceof ApiError && error.code === 'email-already-verified') {
        // Başka sekmede doğrulanmış: sunucu bileşenleri yeniden okunur, bant kalkar.
        router.refresh();
        return;
      }
      toast.error(describeApiError(error, 'E-posta gönderilemedi. Lütfen tekrar deneyin.'));
    } finally {
      setPending(false);
    }
  }

  return (
    <section
      aria-label="E-posta doğrulama uyarısı"
      className="flex flex-col gap-3 rounded-md border border-warning bg-warning-soft p-4 text-sm sm:flex-row sm:items-center"
    >
      <CircleAlert className="size-5 shrink-0 text-warning" aria-hidden="true" />
      <p className="flex-1">
        <strong className="font-semibold">E-posta adresinizi doğrulayın.</strong>{' '}
        {sent ? (
          <span role="status">
            {email} adresine yeni bir bağlantı gönderdik. Gelmezse spam klasörüne de bakın.
          </span>
        ) : (
          <span>
            Doğrulanana dek mağaza bağlama ve maliyet girişi kapalıdır. Bağlantı {email} adresine
            gönderildi.
          </span>
        )}
      </p>
      <Button variant="secondary" size="sm" onClick={onResend} disabled={pending}>
        {pending ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
        Yeniden gönder
      </Button>
    </section>
  );
}
