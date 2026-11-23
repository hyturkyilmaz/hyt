'use client';

import { CircleAlert, CircleCheck, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { AuthCard } from '@/components/auth/auth-card';
import { Button } from '@/components/ui/button';
import { notificationsApi, type UnsubscribeResult } from '@/lib/api/alerts';
import { ApiError } from '@/lib/api/client';
import { describeRateLimitWait } from '@/lib/api/retry-after';
import { RULE_LABELS } from '@/lib/alerts/present';

type State =
  | { status: 'reading' }
  | { status: 'ready' }
  | { status: 'loading' }
  | { status: 'success'; result: UnsubscribeResult }
  | { status: 'invalid' }
  | { status: 'rate-limited'; message: string }
  | { status: 'failed' };

const TOKEN_FORMAT = /^[A-Za-z0-9._~-]{20,512}$/;

const PANEL_HINT = 'Bildirim tercihlerini panelden istediğiniz zaman değiştirebilirsiniz.';

/** Kapatılan kuralların adları: tanınmayan değer (yeni kural) gösterilmez, sayı verilir. */
function describeRules(rules: readonly string[]): string {
  const known = rules.flatMap((rule) =>
    Object.hasOwn(RULE_LABELS, rule) ? [RULE_LABELS[rule as keyof typeof RULE_LABELS]] : [],
  );
  if (known.length === rules.length && known.length > 0) return known.join(', ');
  return rules.length === 1 ? 'Bu uyarı türü' : `${rules.length} uyarı türü`;
}

function describeChannel(channel: string): string {
  return channel === 'push' ? 'anlık bildirimi' : 'e-posta bildirimi';
}

/** Token önce URL parçasından (`#token=...`, e-postadaki bağlantı biçimi), yoksa sorgudan (eski bağlantılar) okunur. */
function readToken(): { token: string | null; present: boolean } {
  const fromHash = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token');
  const raw = fromHash ?? new URLSearchParams(window.location.search).get('token');
  return { token: raw && TOKEN_FORMAT.test(raw) ? raw : null, present: raw !== null };
}

/**
 * Bildirimi tek tıkla kapatma onay sayfası (ADR-0009 §7.5). Oturum gerekmez. Sayfa açılınca OTOMATİK istek YOK:
 * e-posta tarayıcıları ve önizlemeler bağlantıyı açabilir; kapatma yalnız kullanıcı düğmeye basınca yapılır.
 * Token tarayıcıda okunur, bellekte (ref) tutulur ve yalnız isteğin sorgu dizesine konur: sayfada gösterilmez,
 * günlüğe yazılmaz; okunur okunmaz `router.replace` ile adresten silinir.
 * Sunucuya ulaşmama: e-postadaki bağlantı `/bildirim-kapat#token=...` biçimindeyse token URL parçasındadır ve
 * tarayıcı parçayı sunucuya göndermez (Next.js ilk RSC verisine, erişim loglarına ve Referer'a girmez). Eski
 * `?token=` bağlantıları da çalışır ama o durumda token isteğin kendisinde sunucuya gider (geriye uyum).
 */
export function UnsubscribeView() {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<State>({ status: 'reading' });
  const tokenRef = useRef<string | null>(null);
  const acted = useRef(false);
  const read = useRef(false);

  useEffect(() => {
    // Yalnız bir kez okunur: ilk okumadan sonra adres silinir, tekrar okumak token'ı kaybettirirdi.
    if (read.current) return;
    read.current = true;
    const { token, present } = readToken();
    tokenRef.current = token;
    setState(token ? { status: 'ready' } : { status: 'invalid' });
    // Token (parça ya da sorgu) adres çubuğundan, geçmişten ve yer imlerinden silinir; yol korunur.
    if (present) router.replace(pathname, { scroll: false });
  }, [router, pathname]);

  // Sonuç ekranı gelince odak sayfa gövdesine taşınır (düğme kaybolur; klavye ve ekran okuyucu bağlamı bulur).
  useEffect(() => {
    if (!acted.current || state.status === 'reading' || state.status === 'loading') return;
    document.getElementById('main')?.focus();
  }, [state.status]);

  async function onUnsubscribe() {
    const token = tokenRef.current;
    if (!token) return;
    acted.current = true;
    setState({ status: 'loading' });
    try {
      const result = await notificationsApi.unsubscribe(token);
      setState({ status: 'success', result });
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        setState({
          status: 'rate-limited',
          message:
            describeRateLimitWait(error.retryAfterSeconds) ??
            'Çok fazla deneme yaptınız. Biraz sonra tekrar deneyin.',
        });
      } else if (error instanceof ApiError && error.status === 400) {
        setState({ status: 'invalid' });
      } else {
        // Ağ ve sunucu hataları: token geçerli olabilir, kullanıcı yeniden deneyebilir.
        setState({ status: 'failed' });
      }
    }
  }

  if (state.status === 'reading' || state.status === 'ready' || state.status === 'loading') {
    // "reading": adres çubuğundaki token okunana dek (ilk çizim, sunucu çıktısıyla aynı) düğme kapalıdır.
    const loading = state.status === 'loading' || state.status === 'reading';
    return (
      <AuthCard
        title="Bildirimi kapatın"
        description="Bu işlem, e-postanızdaki bildirim türünü kapatır. Giriş yapmanız gerekmez."
      >
        <Button onClick={onUnsubscribe} disabled={loading} aria-disabled={loading}>
          {state.status === 'loading' ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : null}
          {state.status === 'loading' ? 'Kapatılıyor' : 'Bildirimi kapat'}
        </Button>
        <p className="text-sm text-muted-foreground">{PANEL_HINT}</p>
      </AuthCard>
    );
  }

  if (state.status === 'success') {
    return (
      <AuthCard title="Bildirim kapatıldı">
        <p role="status" className="flex items-start gap-3 text-base">
          <CircleCheck className="mt-0.5 size-5 shrink-0 text-profit" aria-hidden="true" />
          <span>
            {describeRules(state.result.rules)} için {describeChannel(state.result.channel)} artık
            gönderilmeyecek. {PANEL_HINT}
          </span>
        </p>
        <Button asChild variant="secondary">
          <Link href="/panel/ayarlar/bildirimler">Bildirim ayarlarına git</Link>
        </Button>
      </AuthCard>
    );
  }

  const title =
    state.status === 'invalid'
      ? 'Bağlantı geçersiz'
      : state.status === 'rate-limited'
        ? 'Çok fazla deneme'
        : 'Bildirim kapatılamadı';
  const message =
    state.status === 'invalid'
      ? `Bağlantı geçersiz ya da süresi dolmuş. ${PANEL_HINT}`
      : state.status === 'rate-limited'
        ? state.message
        : 'Şu an kapatılamadı. İnternet bağlantınızı kontrol edip düğmeye yeniden basın.';
  return (
    <AuthCard title={title}>
      <p
        role="alert"
        className="flex items-start gap-3 rounded-md border border-loss bg-loss-soft p-3 text-sm font-medium text-loss"
      >
        <CircleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <span>
          <span className="sr-only">Hata: </span>
          {message}
        </span>
      </p>
      {state.status === 'failed' ? (
        <Button onClick={onUnsubscribe}>Tekrar dene</Button>
      ) : (
        <Button asChild variant="secondary">
          <Link href="/giris">Girişe git</Link>
        </Button>
      )}
    </AuthCard>
  );
}
