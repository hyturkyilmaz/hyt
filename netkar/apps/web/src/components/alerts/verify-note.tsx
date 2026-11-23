import { VERIFY_NOTE_ID } from '@/components/alerts/blocked';

/** Doğrulanmamış hesapta yazma eylemlerinin neden kapalı olduğunu söyler (düğmelere aria-describedby ile bağlanır). */
export function VerifyNote({ text }: { text: string }) {
  return (
    <p
      id={VERIFY_NOTE_ID}
      className="rounded-md border border-warning bg-warning-soft p-3 text-sm font-medium"
    >
      {text}
    </p>
  );
}

/** Rol (GET /v1/me) okunamadı: yönetici eylemleri gösterilemez; sessizce "viewer" varsayılmaz, kullanıcı bilgilendirilir. */
export function AccessErrorNote() {
  return (
    <p
      role="status"
      className="rounded-md border border-warning bg-warning-soft p-3 text-sm font-medium"
    >
      Yetkiniz okunamadı; susturma ve eşik düzenleme gösterilmiyor. Sayfayı yenileyin.
    </p>
  );
}
