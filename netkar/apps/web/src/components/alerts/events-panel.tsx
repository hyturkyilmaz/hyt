'use client';

import { BellOff, CircleCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { EventCard } from '@/components/alerts/event-card';
import { AccessErrorNote, VerifyNote } from '@/components/alerts/verify-note';
import { EmptyState } from '@/components/panel/empty-state';
import { NoticeBox, type NoticeTone } from '@/components/panel/notice-box';
import { ReportError, ReportSkeleton } from '@/components/profit/shared';
import { Button } from '@/components/ui/button';
import { blockedClass, blockedProps } from '@/components/alerts/blocked';
import {
  alertsApi,
  type AlertEvent,
  type AlertEventList,
  type EventStatus,
  type TransitionBody,
} from '@/lib/api/alerts';
import { ApiError } from '@/lib/api/client';
import { describeRateLimitWait } from '@/lib/api/retry-after';
import { STATUS_LABELS, describeAlertError } from '@/lib/alerts/present';
import type { AlertAccess } from '@/lib/alerts/use-access';
import { formatCount } from '@/lib/format';
import { describeReportError } from '@/lib/profit/errors';
import { retryOnceOnRateLimit } from '@/lib/profit/rate-limit-retry';
import { formatDateTime } from '@/lib/profit/settings-input';
import { usePagedList } from '@/lib/profit/use-paged-list';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 20;

const HEADINGS: Record<EventStatus | 'all', string> = {
  all: 'Tüm uyarılar',
  open: 'Açık uyarılar',
  read: 'Okundu olarak işaretlenenler',
  muted: 'Susturulmuş uyarılar',
  resolved: 'Çözülmüş uyarılar',
};

const EMPTY_DESCRIPTIONS: Record<Exclude<EventStatus, 'open'> | 'all', string> = {
  all: 'Mağaza verileriniz değerlendirildikçe uyarılar burada listelenir.',
  read: 'Okundu işaretlediğiniz uyarılar burada kalır; gerekirse yeniden açabilirsiniz.',
  muted: 'Susturduğunuz uyarılar süre dolana kadar burada bekler.',
  resolved: 'Sorunu giderilen uyarıları sistem kendiliğinden buraya taşır.',
};

interface Notice {
  tone: NoticeTone;
  text: string;
}

/** Liste hatası: 429'da bekleme süresi gösterilir, diğerlerinde rapor ekranlarındaki sade cümle. */
function describeListError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return (
      describeRateLimitWait(error.retryAfterSeconds) ??
      'Çok fazla deneme yaptınız. Birkaç dakika sonra tekrar deneyin.'
    );
  }
  return describeReportError(error);
}

/**
 * Bir durumdaki uyarı olayları (D6 `alert-events?status=`): imleçle "daha fazla yükle", kart eylemleri ve
 * açık sekmede "Tümünü okundu yap". Eylem başarılı olunca kart bu sekmeden çıkar (durumu değiştiği için); 404, 409
 * ve 412'de Türkçe ileti gösterilir ve liste yeniden yüklenir.
 */
export function EventsPanel({
  accountId,
  status,
  access,
  onOpenCount,
  onOpenDelta,
}: {
  accountId: string;
  /** Durum süzgeci; undefined: tüm durumlar (Tümü sekmesi) */
  status: EventStatus | undefined;
  access: AlertAccess;
  /** Sunucudaki açık olay sayısı (sekme etiketi için) */
  onOpenCount: (count: number) => void;
  onOpenDelta: (delta: number) => void;
}) {
  // Eylem sonrası sunucunun döndürdüğü güncel olay (kimliğe göre): kart yerinde güncellenir, süzgece artık
  // uymuyorsa listeden çıkar.
  const [updated, setUpdated] = useState<ReadonlyMap<string, AlertEvent>>(new Map());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  // Çift tıklama ve eşzamanlı eylem kilidi: durum (state) güncellemesi bir sonraki çizimde görünür, ref anında.
  const inFlight = useRef<Set<string>>(new Set());
  const bulkRef = useRef(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const noticeRef = useRef<HTMLDivElement>(null);

  const list = usePagedList<AlertEventList, AlertEvent>({
    enabled: true,
    resetKey: `${accountId}|${status}`,
    fetchPage: (cursor, signal) =>
      retryOnceOnRateLimit(
        () => alertsApi.events(accountId, { status, cursor, limit: PAGE_SIZE }, signal),
        signal,
      ),
    getItems: (page) => page.items,
  });

  const first = list.first;
  useEffect(() => {
    if (!first) return;
    setUpdated(new Map());
    onOpenCount(first.open_count);
  }, [first, onOpenCount]);

  function report(next: Notice) {
    setNotice(next);
    // Kart listeden çıkınca odak kaybolmasın: bildirim bölgesine alınır.
    requestAnimationFrame(() => noticeRef.current?.focus());
  }

  async function transition(event: AlertEvent, body: TransitionBody): Promise<boolean> {
    if (bulkRef.current || inFlight.current.has(event.id)) return false;
    inFlight.current.add(event.id);
    setBusyId(event.id);
    try {
      const result = await alertsApi.transition(accountId, event.id, body);
      const next = result.event;
      setUpdated((prev) => new Map(prev).set(event.id, next));
      if (event.status === 'open' && next.status !== 'open') onOpenDelta(-1);
      if (event.status !== 'open' && next.status === 'open') onOpenDelta(1);
      report({
        tone: 'success',
        text:
          body.to === 'muted'
            ? `Uyarı ${body.muted_days} gün susturuldu.`
            : body.to === 'read'
              ? 'Uyarı okundu olarak işaretlendi.'
              : 'Uyarı yeniden açıldı.',
      });
      return true;
    } catch (error) {
      const described = describeAlertError(error);
      report({ tone: 'error', text: described.text });
      if (described.reload) list.reload();
      return false;
    } finally {
      inFlight.current.delete(event.id);
      setBusyId(null);
    }
  }

  async function readAll() {
    if (!access.verified || bulkRef.current || inFlight.current.size > 0) return;
    bulkRef.current = true;
    setBulkBusy(true);
    try {
      const result = await alertsApi.readAll(accountId);
      const more =
        result.remaining_open > 0
          ? ` Kalan ${formatCount(result.remaining_open)} açık uyarı için tekrar basın (her seferde en çok 500).`
          : '';
      report({
        tone: 'success',
        text:
          result.updated === 0
            ? 'Okundu işaretlenecek açık uyarı yoktu.'
            : `${formatCount(result.updated)} uyarı okundu olarak işaretlendi.${more}`,
      });
      onOpenCount(result.remaining_open);
      list.reload();
    } catch (error) {
      const described = describeAlertError(error);
      report({ tone: 'error', text: described.text });
      if (described.reload) list.reload();
    } finally {
      bulkRef.current = false;
      setBulkBusy(false);
    }
  }

  const items = list.items
    .map((item) => updated.get(item.id) ?? item)
    .filter((item) => status === undefined || item.status === status);
  const urgent = notice?.tone === 'error';
  const box = notice ? (
    <NoticeBox tone={notice.tone} text={notice.text} onDismiss={() => setNotice(null)} />
  ) : null;
  const heading = HEADINGS[status ?? 'all'];
  const openCount = first?.open_count ?? 0;

  return (
    <section aria-labelledby="uyari-liste-baslik" className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 id="uyari-liste-baslik" className="text-2xl font-semibold">
          {heading}
        </h2>
        {(status === 'open' || status === undefined) && list.status === 'ready' && openCount > 0 ? (
          <Button
            variant="secondary"
            className={cn('w-full sm:w-auto', blockedClass(!access.verified))}
            onClick={() => void readAll()}
            aria-busy={bulkBusy || undefined}
            {...blockedProps(!access.verified)}
          >
            Tümünü okundu yap
          </Button>
        ) : null}
      </div>

      {!access.verified ? (
        <VerifyNote text="E-posta adresinizi doğrulayana dek uyarıları okundu işaretleyemez, susturamaz ya da yeniden açamazsınız. Sayfanın üstündeki uyarıdan doğrulama e-postasını yeniden isteyebilirsiniz." />
      ) : null}

      {access.status === 'error' ? <AccessErrorNote /> : null}

      {/* Boş canlı bölge sayfada kalıcıdır; metin sonradan konunca ekran okuyucular okur. */}
      <div ref={noticeRef} tabIndex={-1} className="focus:outline-none">
        <div role="status">{notice && !urgent ? box : null}</div>
        {urgent ? <div role="alert">{box}</div> : null}
      </div>

      {list.status === 'loading' ? <ReportSkeleton rows={3} /> : null}
      {list.status === 'error' ? (
        <ReportError
          title="Uyarılar yüklenemedi"
          message={describeListError(list.error)}
          onRetry={list.reload}
        />
      ) : null}
      {list.status === 'ready' && items.length === 0 && !list.hasMore ? (
        status === 'open' ? (
          <EmptyState
            Icon={CircleCheck}
            title="Açık uyarı yok"
            description={
              first?.last_evaluated_at
                ? `Son değerlendirme: ${formatDateTime(first.last_evaluated_at)}.`
                : 'Henüz değerlendirme yapılmadı. Mağaza verileri geldikçe uyarılar burada görünür.'
            }
          />
        ) : (
          <EmptyState
            Icon={BellOff}
            title={status === undefined ? 'Henüz uyarı yok' : `${STATUS_LABELS[status]} uyarı yok`}
            description={EMPTY_DESCRIPTIONS[status ?? 'all']}
          />
        )
      ) : null}
      {list.status === 'ready' && items.length > 0 ? (
        <>
          {list.restarted ? (
            <p className="text-sm text-muted-foreground" role="status">
              Liste güncellendi, baştan yüklendi.
            </p>
          ) : null}
          <ul role="list" className="grid list-none items-start gap-4 lg:grid-cols-2">
            {items.map((event) => (
              <li key={event.id} className="flex">
                <EventCard
                  event={event}
                  access={access}
                  busy={busyId === event.id || bulkBusy}
                  onTransition={transition}
                />
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {list.moreError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          {describeListError(list.moreError)}
        </p>
      ) : null}
      {list.status === 'ready' && list.hasMore ? (
        <Button
          variant="secondary"
          className="w-full sm:w-auto sm:self-start"
          onClick={list.loadMore}
          disabled={list.loadingMore}
        >
          {list.loadingMore ? 'Yükleniyor' : 'Daha fazla yükle'}
        </Button>
      ) : null}
    </section>
  );
}
