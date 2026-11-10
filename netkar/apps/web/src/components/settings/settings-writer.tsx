'use client';

import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { ApiError, describeApiError } from '@/lib/api/client';
import {
  asPastChangeUnconfirmed,
  isRecordEnded,
  isRevisionConflict,
  type WriteInfo,
} from '@/lib/api/profit-settings';
import type { ConfirmTopic } from '@/lib/profit/settings-present';
import { settingsKeys } from '@/components/settings/use-settings-data';

export type SettingsScope = 'kargo' | 'hizmet-bedeli' | 'desi' | 'giderler';

export interface SendGuards {
  expectedRevision?: number;
  /** K43 onayı: etki tarihi (YYYY-AA-GG) ya da tarihsizde "all" */
  confirmAffectsFrom?: string;
}

/** Bir yazma işi: ne gönderileceği, onay penceresi metni ve sonuç geri çağrıları. */
export interface WriteJob {
  scope: SettingsScope;
  topic: ConfirmTopic;
  successText: (info: WriteInfo) => string;
  send: (guards: SendGuards) => Promise<WriteInfo>;
  /** "Yalnız bugünden itibaren uygula" (ADR-0007 §5.2): başlangıcı bugün olan yeni sürüm, onay gerekmez */
  sendFromToday?: (guards: { expectedRevision?: number }) => Promise<WriteInfo>;
  onDone?: (info: WriteInfo) => void;
  /** 422: alan hataları (form alanın yanında gösterir) */
  onInvalid?: (error: ApiError) => void;
  /** 409 kayıt kapandı ya da ayarlar değişti: ekran yenilendi */
  onStale?: (reason: 'record-ended' | 'revision-conflict') => void;
  /**
   * İstemci onayı (WCAG 3.3.4): verilirse yazım HEMEN gönderilmez; önce bu metinle pencere açılır. Geri çekme gibi
   * geri alınamaz işlemlerde kullanılır. Onaydan sonra gönderim sunucu 409 verirse aynı pencere ADR metnine geçer.
   */
  clientConfirm?: { title: string; body: string; applyLabel: string };
}

export interface SettingsNotice {
  id: number;
  scope: SettingsScope;
  tone: 'success' | 'info' | 'warning' | 'error';
  text: string;
}

export interface ConfirmState {
  job: WriteJob;
  /** client: istemci onayı (henüz istek yok); past-change: sunucu 409'u, ADR-0007 §5.2 metni */
  stage: 'client' | 'past-change';
  affectsFrom: string | null;
  currentRevision: number | undefined;
  busy: boolean;
  /** Onay penceresindeki ikinci 409'da etki tarihi değiştiyse kısa not */
  changed: boolean;
}

interface WriterValue {
  /** Kayıt sürerken ikinci yazım başlatılmaz */
  pending: boolean;
  notice: SettingsNotice | null;
  dismissNotice: () => void;
  confirm: ConfirmState | null;
  run: (job: WriteJob) => Promise<void>;
  confirmApply: () => Promise<void>;
  confirmFromToday: () => Promise<void>;
  confirmCancel: () => void;
  /** Pencere kapanınca odağı tetikleyiciye (yoksa bölüm başlığına) döndürür; pencerenin onCloseAutoFocus'u çağırır. */
  restoreFocus: () => void;
}

const WriterContext = createContext<WriterValue | null>(null);

export function useSettingsWriter(): WriterValue {
  const value = useContext(WriterContext);
  if (!value) throw new Error('useSettingsWriter, SettingsWriterProvider içinde kullanılmalı.');
  return value;
}

const DATE_UNKNOWN_TEXT =
  'Değişikliğin etkileyeceği tarih alınamadı. Sayfayı yenileyip tekrar deneyin; hiçbir şey kaydedilmedi.';

/** Yazma hatası metni: yetki ve oturum hataları CSRF metninden ayrılır (AF-10). */
function describeWriteError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return 'Oturumunuz sona erdi. Yeniden giriş yapın; girdiğiniz değerler bu sekmede duruyor.';
  }
  if (error instanceof ApiError && error.status === 403 && error.code === 'forbidden') {
    return 'Bu işlem için yetkiniz yok. Ayarları yalnız hesabın sahibi ya da yöneticisi değiştirebilir.';
  }
  return describeApiError(
    error,
    'Kaydedilemedi. Girdiğiniz değerleri kontrol edip tekrar deneyin.',
  );
}

const RECORD_ENDED_TEXT = 'Bu kayıt başka bir değişiklikle güncellendi. Ekranı yeniledik.';
const REVISION_CONFLICT_TEXT =
  'Ayarlar siz düzenlerken başka biri tarafından değiştirildi. Ekranı yeniledik; değişikliğinizi kontrol edip tekrar uygulayın.';

export function SettingsWriterProvider({
  accountId,
  revision,
  children,
}: {
  accountId: string;
  /** Ekrandaki ayar sürümü; her yazımda `expected_revision` olarak gönderilir (AB-03) */
  revision: number;
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<SettingsNotice | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const noticeId = useRef(0);
  const revisionRef = useRef(revision);
  useEffect(() => {
    revisionRef.current = revision;
  }, [revision]);
  const busyRef = useRef(false);
  const confirmRef = useRef<ConfirmState | null>(null);
  useEffect(() => {
    confirmRef.current = confirm;
  }, [confirm]);
  // Odak: işi başlatan öğe (tetikleyici) ve pencere kapanınca nereye dönüleceği (AF-02, WCAG 2.4.3)
  const triggerRef = useRef<HTMLElement | null>(null);
  const focusScopeRef = useRef<SettingsScope>('kargo');
  const focusPlanRef = useRef<'trigger' | 'heading'>('trigger');

  const restoreFocus = useCallback(() => {
    const trigger = triggerRef.current;
    const usable =
      focusPlanRef.current === 'trigger' &&
      trigger !== null &&
      trigger.isConnected &&
      !(trigger instanceof HTMLButtonElement && trigger.disabled);
    const target = usable ? trigger : document.getElementById(`${focusScopeRef.current}-baslik`);
    target?.focus();
  }, []);

  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: settingsKeys.settings(accountId) }),
      queryClient.invalidateQueries({ queryKey: settingsKeys.carriers(accountId) }),
    ]);
  }, [accountId, queryClient]);

  const showNotice = useCallback(
    (scope: SettingsScope, tone: SettingsNotice['tone'], text: string) => {
      noticeId.current += 1;
      setNotice({ id: noticeId.current, scope, tone, text });
    },
    [],
  );

  const finish = useCallback(
    async (job: WriteJob, info: WriteInfo) => {
      // Başarıda form kapanır ve tetikleyici kalkar: odak bölüm başlığına gider. Pencere açıksa kapanışta
      // (onCloseAutoFocus), değilse hemen.
      focusPlanRef.current = 'heading';
      focusScopeRef.current = job.scope;
      const hadDialog = confirmRef.current !== null;
      setConfirm(null);
      if (!hadDialog) restoreFocus();
      await refresh();
      showNotice(
        job.scope,
        info.changed ? 'success' : 'info',
        info.changed
          ? job.successText(info)
          : 'Değişiklik yok: bu ayar zaten bu değerlerle kayıtlı.',
      );
      job.onDone?.(info);
    },
    [refresh, restoreFocus, showNotice],
  );

  /** Ortak hata yolu; true: 409 onay penceresi açıldı ya da açık tutuldu. */
  const fail = useCallback(
    async (job: WriteJob, error: unknown, fromDialog: boolean): Promise<void> => {
      const unconfirmed = asPastChangeUnconfirmed(error);
      if (unconfirmed) {
        // Tarihli bir yazımda etki tarihi yoksa metin yanlış olurdu: pencere açılmaz (AF-16)
        if (job.topic !== 'defaults' && unconfirmed.affectsFrom === null) {
          setConfirm(null);
          showNotice(job.scope, 'error', DATE_UNKNOWN_TEXT);
          return;
        }
        setConfirm((previous) => ({
          job,
          stage: 'past-change',
          affectsFrom: unconfirmed.affectsFrom,
          currentRevision: unconfirmed.currentRevision ?? revisionRef.current,
          busy: false,
          changed:
            fromDialog &&
            previous !== null &&
            previous.stage === 'past-change' &&
            previous.affectsFrom !== unconfirmed.affectsFrom,
        }));
        return;
      }
      setConfirm(null);
      if (isRecordEnded(error)) {
        await refresh();
        showNotice(job.scope, 'warning', RECORD_ENDED_TEXT);
        job.onStale?.('record-ended');
        return;
      }
      if (isRevisionConflict(error)) {
        await refresh();
        showNotice(job.scope, 'warning', REVISION_CONFLICT_TEXT);
        job.onStale?.('revision-conflict');
        return;
      }
      if (error instanceof ApiError && error.status === 422 && job.onInvalid) {
        job.onInvalid(error);
        return;
      }
      showNotice(job.scope, 'error', describeWriteError(error));
    },
    [refresh, showNotice],
  );

  const run = useCallback(
    async (job: WriteJob) => {
      if (busyRef.current) return;
      const active = document.activeElement;
      triggerRef.current =
        active instanceof HTMLElement && active !== document.body ? active : null;
      focusPlanRef.current = 'trigger';
      focusScopeRef.current = job.scope;
      if (job.clientConfirm) {
        setNotice(null);
        setConfirm({
          job,
          stage: 'client',
          affectsFrom: null,
          currentRevision: undefined,
          busy: false,
          changed: false,
        });
        return;
      }
      busyRef.current = true;
      setPending(true);
      setNotice(null);
      try {
        // İlk deneme onaysızdır: ilk giriş istisnasında gönderilmiş onay bile 409 üretir (K43, YT-07).
        const info = await job.send({ expectedRevision: revisionRef.current });
        await finish(job, info);
      } catch (error) {
        await fail(job, error, false);
      } finally {
        busyRef.current = false;
        setPending(false);
      }
    },
    [fail, finish],
  );

  const confirmApply = useCallback(async () => {
    if (!confirm || busyRef.current) return;
    busyRef.current = true;
    setConfirm({ ...confirm, busy: true, changed: false });
    try {
      const info = await confirm.job.send(
        confirm.stage === 'client'
          ? // İstemci onayından sonraki ilk gönderim de onaysızdır: geçmişi etkiliyorsa sunucu 409 verir (K43)
            { expectedRevision: revisionRef.current }
          : {
              // 409'daki sürüm de geri gönderilir: araya giren başka değişiklik onayın dışında kalmaz (AB-03)
              expectedRevision: confirm.currentRevision ?? revisionRef.current,
              confirmAffectsFrom: confirm.affectsFrom ?? 'all',
            },
      );
      await finish(confirm.job, info);
    } catch (error) {
      await fail(confirm.job, error, true);
    } finally {
      busyRef.current = false;
    }
  }, [confirm, fail, finish]);

  const confirmFromToday = useCallback(async () => {
    if (!confirm || !confirm.job.sendFromToday || busyRef.current) return;
    busyRef.current = true;
    setConfirm({ ...confirm, busy: true, changed: false });
    try {
      const info = await confirm.job.sendFromToday({
        expectedRevision: confirm.currentRevision ?? revisionRef.current,
      });
      await finish(confirm.job, info);
    } catch (error) {
      await fail(confirm.job, error, true);
    } finally {
      busyRef.current = false;
    }
  }, [confirm, fail, finish]);

  const confirmCancel = useCallback(() => {
    if (busyRef.current) return;
    setConfirm(null);
  }, []);

  const dismissNotice = useCallback(() => setNotice(null), []);

  const value = useMemo<WriterValue>(
    () => ({
      pending,
      notice,
      dismissNotice,
      confirm,
      run,
      confirmApply,
      confirmFromToday,
      confirmCancel,
      restoreFocus,
    }),
    [
      pending,
      notice,
      dismissNotice,
      confirm,
      run,
      confirmApply,
      confirmFromToday,
      confirmCancel,
      restoreFocus,
    ],
  );

  return <WriterContext.Provider value={value}>{children}</WriterContext.Provider>;
}
