'use client';

import { Loader2 } from 'lucide-react';
import { useEffect, useRef } from 'react';

import { useSettingsWriter } from '@/components/settings/settings-writer';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { confirmCopy } from '@/lib/profit/settings-present';

/**
 * K43 onay penceresi (ADR-0007 §5.2 ayar ekranı madde 1): metinler ADR'den birebir. Birincil "Değişikliği uygula"
 * 409'daki `affects_from` ve `current_revision` ile yeniden gönderir; ikincil "Yalnız bugünden itibaren uygula"
 * yalnız tarife, hizmet bedeli ve gider eklemede vardır (başlangıcı bugün olan yeni sürüm, onay gerekmez).
 * Geri çekme önce istemci onayı alır (WCAG 3.3.4); sunucu 409 verirse aynı pencere ADR metnine geçer.
 */
export function ConfirmPastChangeDialog() {
  const { confirm, confirmApply, confirmFromToday, confirmCancel, restoreFocus } =
    useSettingsWriter();
  const clientStage = confirm?.stage === 'client';
  const copy = confirm
    ? clientStage && confirm.job.clientConfirm
      ? confirm.job.clientConfirm
      : confirmCopy(confirm.job.topic, confirm.affectsFrom)
    : null;
  const busy = confirm?.busy ?? false;
  const cancelRef = useRef<HTMLButtonElement>(null);
  const open = confirm !== null;

  // Pencere açıkken yeni bir istek bitince (ör. istemci onayından ADR metnine geçiş) odak güvenli düğmeye döner:
  // devre dışı kalan düğmede kalmaz, ekran okuyucu yeni metni yeniden okur.
  useEffect(() => {
    if (open && !busy) cancelRef.current?.focus();
  }, [open, busy, confirm?.stage, confirm?.affectsFrom]);

  return (
    <Dialog
      open={confirm !== null}
      onOpenChange={(open) => {
        if (!open) confirmCancel();
      }}
    >
      <DialogContent
        // Veri değiştiren onay: alertdialog; dışarı tıklamak ya da odak kaybı kapatmaz, yalnız Vazgeç, Esc ve Kapat
        role="alertdialog"
        aria-busy={busy}
        onPointerDownOutside={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
        // Odak tetikleyiciye, o kalkmışsa bölüm başlığına döner (WCAG 2.4.3)
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          restoreFocus();
        }}
      >
        {confirm && copy ? (
          <>
            <DialogHeader>
              <DialogTitle>{copy.title}</DialogTitle>
              <DialogDescription>{copy.body}</DialogDescription>
            </DialogHeader>
            {confirm.changed && !clientStage ? (
              <p role="status" className="text-sm font-medium text-warning">
                Etkilenen tarih değişti. Yukarıdaki metni yeniden okuyup onaylayın.
              </p>
            ) : null}
            <DialogFooter>
              <Button ref={cancelRef} variant="secondary" onClick={confirmCancel} disabled={busy}>
                Vazgeç
              </Button>
              {!clientStage && confirm.job.sendFromToday ? (
                <Button variant="secondary" onClick={() => void confirmFromToday()} disabled={busy}>
                  Yalnız bugünden itibaren uygula
                </Button>
              ) : null}
              <Button onClick={() => void confirmApply()} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
                {clientStage && confirm.job.clientConfirm
                  ? confirm.job.clientConfirm.applyLabel
                  : 'Değişikliği uygula'}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
