'use client';

import { ShieldCheck, ShieldOff } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { RecoveryCodesPanel } from '@/components/security/recovery-codes-panel';
import { TotpManageForm } from '@/components/security/totp-manage-form';
import { TotpSetupFlow } from '@/components/security/totp-setup-flow';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { authApi } from '@/lib/api/endpoints';

type View =
  | { kind: 'idle' }
  | { kind: 'setup' }
  | { kind: 'disable' }
  | { kind: 'regenerate' }
  | { kind: 'codes'; codes: string[] };

/**
 * Güvenlik ayarları: iki adımlı doğrulama (TOTP) kurma, kapatma ve kurtarma kodlarını yenileme.
 * Her değişiklik güncel parola (ve açıkken güncel kod) ister; durum sunucudan (me) gelir ve işlemlerden sonra
 * sunucu bileşenleri yenilenir.
 */
export function SecurityView({
  initialTotpEnabled,
  initialRecoveryCodesRemaining,
}: {
  initialTotpEnabled: boolean;
  initialRecoveryCodesRemaining: number;
}) {
  const router = useRouter();
  const [enabled, setEnabled] = useState(initialTotpEnabled);
  const [remaining, setRemaining] = useState(initialRecoveryCodesRemaining);
  const [view, setView] = useState<View>({ kind: 'idle' });

  const lowOnCodes = enabled && remaining <= 3;

  return (
    <Card id="iki-adim" as="section" aria-labelledby="iki-adim-baslik">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle as="h2" id="iki-adim-baslik" className="flex items-center gap-2">
            {enabled ? (
              <ShieldCheck className="size-5 text-profit" aria-hidden="true" />
            ) : (
              <ShieldOff className="size-5 text-muted-foreground" aria-hidden="true" />
            )}
            İki adımlı doğrulama
          </CardTitle>
          <Badge variant={enabled ? 'profit' : 'neutral'} role="status">
            {enabled ? 'Açık' : 'Kapalı'}
          </Badge>
        </div>
        <CardDescription>
          Girişte parolanıza ek olarak doğrulama uygulamanızdaki kodu ister. Hesabınızı parola
          çalınsa bile korur.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {view.kind === 'idle' ? (
          enabled ? (
            <>
              <p
                role={lowOnCodes ? 'alert' : undefined}
                className={
                  lowOnCodes
                    ? 'rounded-md border border-warning bg-warning-soft p-3 text-sm font-medium'
                    : 'text-base'
                }
              >
                Kalan kurtarma kodu: <span className="num font-semibold">{remaining}</span>
                {lowOnCodes ? ' - kodlarınız azaldı, yenilemenizi öneririz.' : null}
              </p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button variant="secondary" onClick={() => setView({ kind: 'regenerate' })}>
                  Kurtarma kodlarını yenile
                </Button>
                <Button variant="secondary" onClick={() => setView({ kind: 'disable' })}>
                  İki adımlı doğrulamayı kapat
                </Button>
              </div>
            </>
          ) : (
            <div>
              <Button onClick={() => setView({ kind: 'setup' })}>Kurulumu başlat</Button>
            </div>
          )
        ) : null}

        {view.kind === 'setup' ? (
          <TotpSetupFlow
            onCancel={() => setView({ kind: 'idle' })}
            onEnabled={(count) => {
              setEnabled(true);
              setRemaining(count);
              setView({ kind: 'idle' });
              toast.success('İki adımlı doğrulama açıldı.');
              router.refresh();
            }}
          />
        ) : null}

        {view.kind === 'regenerate' ? (
          <TotpManageForm
            title="Kurtarma kodlarını yenile"
            description="Yeni 10 kod üretilir, eski kodlar geçersiz olur. Güvenlik için bu cihaz dışındaki tüm oturumlar kapatılır."
            submitLabel="Yeni kodlar üret"
            pendingLabel="Üretiliyor"
            failureMessage="Kodlar yenilenemedi. Lütfen tekrar deneyin."
            onCancel={() => setView({ kind: 'idle' })}
            onSubmit={async (values) => {
              const result = await authApi.regenerateRecoveryCodes(values);
              setRemaining(result.recovery_codes.length);
              setView({ kind: 'codes', codes: result.recovery_codes });
            }}
          />
        ) : null}

        {view.kind === 'disable' ? (
          <TotpManageForm
            title="İki adımlı doğrulamayı kapat"
            description="Kapatınca girişte yalnız parola istenir ve kurtarma kodları geçersiz olur. Güvenlik için bu cihaz dışındaki tüm oturumlar kapatılır."
            submitLabel="Doğrulamayı kapat"
            pendingLabel="Kapatılıyor"
            failureMessage="İki adımlı doğrulama kapatılamadı. Lütfen tekrar deneyin."
            onCancel={() => setView({ kind: 'idle' })}
            onSubmit={async (values) => {
              await authApi.totpDisable(values);
              setEnabled(false);
              setRemaining(0);
              setView({ kind: 'idle' });
              toast.success('İki adımlı doğrulama kapatıldı.');
              router.refresh();
            }}
          />
        ) : null}

        {view.kind === 'codes' ? (
          <RecoveryCodesPanel
            codes={view.codes}
            onDone={() => {
              setView({ kind: 'idle' });
              router.refresh();
            }}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
