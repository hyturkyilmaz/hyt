import { CheckCircle2, Info, TriangleAlert, X } from 'lucide-react';

import { cn } from '@/lib/utils';

export type NoticeTone = 'success' | 'info' | 'warning' | 'error';

const NOTICE_TONES = {
  success: { Icon: CheckCircle2, className: 'bg-profit-soft text-profit' },
  info: { Icon: Info, className: 'bg-info-soft text-info' },
  warning: { Icon: TriangleAlert, className: 'bg-warning-soft text-warning' },
  error: { Icon: TriangleAlert, className: 'bg-loss-soft text-loss' },
} as const;

/**
 * Satır içi bildirim kutusu (ikon + metin + kapat düğmesi). Ayarlar ve uyarılar ekranları paylaşır; canlı bölge
 * (`role="status"` / `role="alert"`) çağıran tarafta kurulur.
 */
export function NoticeBox({
  tone,
  text,
  onDismiss,
}: {
  tone: NoticeTone;
  text: string;
  onDismiss: () => void;
}) {
  const { Icon, className } = NOTICE_TONES[tone];
  return (
    <div className={cn('flex items-start gap-2 rounded-lg p-3 text-sm font-medium', className)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p className="flex-1">{text}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="-m-2 inline-flex size-touch shrink-0 items-center justify-center rounded-md hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="size-4" aria-hidden="true" />
        <span className="sr-only">Bildirimi kapat</span>
      </button>
    </div>
  );
}
