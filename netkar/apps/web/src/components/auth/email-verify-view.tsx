'use client';

import { CircleAlert, CircleCheck, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import { AuthCard } from '@/components/auth/auth-card';
import { Button } from '@/components/ui/button';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';

type State = { status: 'loading' } | { status: 'success' } | { status: 'error'; message: string };

const MISSING_TOKEN =
  'Doğrulama bağlantısı eksik ya da bozuk. E-postadaki bağlantıyı olduğu gibi açın.';

/**
 * E-posta doğrulama: sayfa açılınca token API'ye bir kez gönderilir (POST /v1/auth/email/verify).
 * Token tek kullanımlıktır; React Strict Mode'un ikinci efekt çalıştırması ref ile engellenir ki
 * ikinci istek "kullanılmış" hatasıyla başarılı sonucu ezmesin.
 */
export function EmailVerifyView({ token }: { token: string | null }) {
  const [state, setState] = useState<State>(
    token ? { status: 'loading' } : { status: 'error', message: MISSING_TOKEN },
  );
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    authApi
      .verifyEmail({ token })
      .then(() => setState({ status: 'success' }))
      .catch((error: unknown) => {
        const fallback =
          error instanceof ApiError && error.code === 'invalid-verification-token'
            ? 'Bu bağlantının süresi dolmuş veya daha önce kullanılmış. E-postanız zaten doğrulanmış olabilir; değilse giriş yapıp panelden yeni bir doğrulama e-postası isteyin.'
            : 'E-posta doğrulanamadı. Lütfen bağlantıyı yeniden açın.';
        setState({ status: 'error', message: describeApiError(error, fallback) });
      });
  }, [token]);

  if (state.status === 'loading') {
    return (
      <AuthCard title="E-postanız doğrulanıyor">
        <p role="status" className="flex items-center gap-3 text-base">
          <Loader2 className="size-5 shrink-0 animate-spin" aria-hidden="true" />
          <span>Lütfen bekleyin, bağlantı kontrol ediliyor.</span>
        </p>
      </AuthCard>
    );
  }

  if (state.status === 'success') {
    return (
      <AuthCard title="E-postanız doğrulandı">
        <p role="status" className="flex items-start gap-3 text-base">
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-profit" aria-hidden="true" />
          <span>Teşekkürler. Artık mağazanızı bağlayabilir ve maliyetlerinizi girebilirsiniz.</span>
        </p>
        <Button asChild>
          <Link href="/panel">Panele git</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="E-posta doğrulanamadı">
      <p
        role="alert"
        className="flex items-start gap-3 rounded-md border border-loss bg-loss-soft p-3 text-sm font-medium text-loss"
      >
        <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <span>
          <span className="sr-only">Hata: </span>
          {state.message}
        </span>
      </p>
      <Button asChild variant="secondary">
        <Link href="/giris">Girişe git</Link>
      </Button>
    </AuthCard>
  );
}
