'use client';

import { CircleAlert, CircleCheck, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { AuthCard } from '@/components/auth/auth-card';
import { Button } from '@/components/ui/button';
import { ApiError, describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';

type State =
  | { status: 'ready' }
  | { status: 'loading' }
  | { status: 'success' }
  | { status: 'error'; message: string };

const MISSING_TOKEN =
  'Doğrulama bağlantısı eksik ya da bozuk. E-postadaki bağlantıyı olduğu gibi açın.';

/**
 * E-posta doğrulama: otomatik istek YOK. Bağlantıyı açmak hesabı doğrulamaz (e-posta tarayıcıları ve
 * önizlemeler bağlantıyı açabilir); kullanıcı "E-postamı doğrula" düğmesine basınca token oturumla birlikte
 * API'ye gider (POST /v1/auth/email/verify). Token okunur okunmaz adres çubuğundan silinir
 * (history.replaceState): geçmişe, yer imine ve ekran görüntüsüne düşmez.
 */
export function EmailVerifyView({ token }: { token: string | null }) {
  const [state, setState] = useState<State>(
    token ? { status: 'ready' } : { status: 'error', message: MISSING_TOKEN },
  );

  useEffect(() => {
    if (!token) return;
    // Yalnız sorgu dizesi silinir; yol ve durum korunur.
    window.history.replaceState(window.history.state, '', window.location.pathname);
  }, [token]);

  async function onVerify() {
    if (!token) return;
    setState({ status: 'loading' });
    try {
      await authApi.verifyEmail({ token });
      setState({ status: 'success' });
    } catch (error) {
      const fallback =
        error instanceof ApiError && error.status === 401
          ? 'Oturumunuz sona ermiş. Girişe gidin ve e-postadaki bağlantıyı yeniden açın.'
          : error instanceof ApiError && error.code === 'invalid-verification-token'
            ? 'Bu bağlantı geçersiz, süresi dolmuş, daha önce kullanılmış ya da şu an giriş yaptığınız hesaba ait değil. Kayıt olurken kullandığınız hesapla giriş yaptığınızdan emin olun; gerekirse panelden yeni bir doğrulama e-postası isteyin.'
            : 'E-posta doğrulanamadı. Lütfen tekrar deneyin.';
      setState({ status: 'error', message: describeApiError(error, fallback) });
    }
  }

  if (state.status === 'ready' || state.status === 'loading') {
    const loading = state.status === 'loading';
    return (
      <AuthCard
        title="E-posta adresinizi doğrulayın"
        description="Bu işlem, giriş yaptığınız hesabın e-posta adresini doğrular. Hesabı siz oluşturduysanız devam edin."
      >
        <Button onClick={onVerify} disabled={loading} aria-disabled={loading}>
          {loading ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
          {loading ? 'Doğrulanıyor' : 'E-postamı doğrula'}
        </Button>
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
