'use client';

import { Loader2 } from 'lucide-react';

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
 */
export function ConfirmPastChangeDialog() {
  const { confirm, confirmApply, confirmFromToday, confirmCancel } = useSettingsWriter();
  const copy = confirm ? confirmCopy(confirm.job.topic, confirm.affectsFrom) : null;
  const busy = confirm?.busy ?? false;

  return (
    <Dialog
      open={confirm !== null}
      onOpenChange={(open) => {
        if (!open) confirmCancel();
      }}
    >
      <DialogContent aria-busy={busy}>
        {confirm && copy ? (
          <>
            <DialogHeader>
              <DialogTitle>{copy.title}</DialogTitle>
              <DialogDescription>{copy.body}</DialogDescription>
            </DialogHeader>
            {confirm.changed ? (
              <p role="status" className="text-sm font-medium text-warning">
                Etkilenen tarih değişti. Yukarıdaki metni yeniden okuyup onaylayın.
              </p>
            ) : null}
            <DialogFooter>
              <Button variant="secondary" onClick={confirmCancel} disabled={busy}>
                Vazgeç
              </Button>
              {confirm.job.sendFromToday ? (
                <Button variant="secondary" onClick={() => void confirmFromToday()} disabled={busy}>
                  Yalnız bugünden itibaren uygula
                </Button>
              ) : null}
              <Button onClick={() => void confirmApply()} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
                Değişikliği uygula
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
