'use client';

import { CheckCircle2, Download, FileSpreadsheet, Loader2, TriangleAlert } from 'lucide-react';
import { forwardRef, useEffect, useId, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import {
  IMPORT_MAX_BYTES,
  IMPORT_MAX_ROWS,
  productCostsApi,
  type ImportReport,
} from '@/lib/api/product-costs';
import {
  TEMPLATE_COLUMNS,
  checkImportFile,
  columnLabel,
  describeImportError,
  describeTemplateError,
  parseImportReport,
  reportHeadline,
  snapshotFile,
  FILE_READ_MESSAGE,
  FileReadError,
  TEMPLATE_TRUNCATED_NOTE,
} from '@/lib/profit/cost-present';
import { cn } from '@/lib/utils';

type Phase =
  | { kind: 'idle' }
  | { kind: 'checking' }
  | { kind: 'preview'; report: ImportReport; notSaved: boolean }
  | { kind: 'applying'; report: ImportReport }
  | { kind: 'done'; report: ImportReport };

const SHOWN_ERRORS = 20;

/**
 * Toplu maliyet yükleme: dosya seç, sunucunun kuru deneme raporunu (hiçbir şey yazılmaz) oku, onaylayınca kaydet.
 * Hatalı satır varsa varsayılan hiçbir şey kaydedilmez; yalnız açık "geçerli satırları kaydet" düğmesi
 * `allow_partial=true` gönderir.
 */
export function CostImportPanel({
  accountId,
  onImported,
  disabled = false,
}: {
  accountId: string;
  onImported: () => void;
  /** Rol yüklenirken denetimler devre dışı görünür */
  disabled?: boolean;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [showAll, setShowAll] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templateTruncated, setTemplateTruncated] = useState(false);
  const reportRef = useRef<HTMLElement>(null);
  const chooseToken = useRef(0);
  const busy = phase.kind === 'checking' || phase.kind === 'applying' || disabled;

  // Kontrol ve kayıt bitince düğmeler kalkar; odak rapora taşınır (WCAG 2.4.3), başlık okunur.
  useEffect(() => {
    if (phase.kind === 'preview' || phase.kind === 'done') reportRef.current?.focus();
  }, [phase.kind]);

  async function downloadTemplate() {
    setTemplateBusy(true);
    setTemplateError(null);
    setTemplateTruncated(false);
    try {
      const template = await productCostsApi.template(accountId);
      const url = URL.createObjectURL(template.blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = template.filename;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setTemplateTruncated(template.truncated);
    } catch (e) {
      setTemplateError(describeTemplateError(e));
    } finally {
      setTemplateBusy(false);
    }
  }

  function reset() {
    chooseToken.current += 1;
    setFile(null);
    setFileError(null);
    setError(null);
    setPhase({ kind: 'idle' });
    setShowAll(false);
    if (inputRef.current) inputRef.current.value = '';
  }

  async function choose(next: File | null) {
    const ticket = (chooseToken.current += 1);
    setError(null);
    setPhase({ kind: 'idle' });
    setShowAll(false);
    setFile(null);
    setFileError(null);
    if (!next) return;
    const check = checkImportFile(next);
    if (!check.ok) {
      setFileError(check.message);
      return;
    }
    // Dosya bir kez okunur: kontrol ile kayıt arasında diskte değişse de onaylanan içerik gönderilir (ME-08).
    try {
      const snapshot = await snapshotFile(next);
      if (chooseToken.current === ticket) setFile(snapshot);
    } catch (e) {
      if (chooseToken.current === ticket) {
        setFileError(e instanceof FileReadError ? FILE_READ_MESSAGE : describeImportError(e));
      }
    }
  }

  async function preview() {
    if (!file) return;
    setError(null);
    setPhase({ kind: 'checking' });
    try {
      const raw = await productCostsApi.importFile(accountId, file, {
        dryRun: true,
        allowPartial: false,
      });
      const report = parseImportReport(raw);
      if (!report) {
        setError('Sunucu yanıtı beklenenden farklı geldi. Tekrar deneyin.');
        setPhase({ kind: 'idle' });
        return;
      }
      setPhase({ kind: 'preview', report, notSaved: false });
    } catch (e) {
      setError(describeImportError(e));
      setPhase({ kind: 'idle' });
    }
  }

  async function apply(report: ImportReport, allowPartial: boolean) {
    if (!file) return;
    setError(null);
    setPhase({ kind: 'applying', report });
    try {
      const raw = await productCostsApi.importFile(accountId, file, {
        dryRun: false,
        allowPartial,
      });
      const result = parseImportReport(raw);
      onImported();
      if (!result) {
        setError(
          'Kayıt tamamlanmış olabilir ama sunucu yanıtı okunamadı. Ürün listesini kontrol edin.',
        );
        setPhase({ kind: 'idle' });
        return;
      }
      setPhase({ kind: 'done', report: result });
    } catch (e) {
      // Kayıt sırasında hata çıkan satırlar varsa sunucu raporu 422 ile döner; hiçbir şey kaydedilmemiştir.
      const failed =
        e instanceof ApiError && e.code === 'import-validation-failed'
          ? parseImportReport(e.report)
          : null;
      if (failed) {
        setPhase({ kind: 'preview', report: failed, notSaved: true });
      } else {
        setError(describeImportError(e));
        setPhase({ kind: 'preview', report, notSaved: false });
      }
    }
  }

  const report = phase.kind === 'idle' || phase.kind === 'checking' ? null : phase.report;

  return (
    <Card as="section" aria-labelledby="toplu-yukle-baslik">
      <CardHeader>
        <h2 id="toplu-yukle-baslik" className="flex items-center gap-2 text-xl font-semibold">
          <FileSpreadsheet className="size-5 text-primary" aria-hidden="true" />
          Toplu maliyet yükle
        </h2>
        <p className="text-sm text-muted-foreground">
          Çok ürününüz varsa maliyetleri dosyadan yükleyin. Önce dosya kontrol edilir, siz
          onaylamadan hiçbir şey kaydedilmez.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button
            variant="secondary"
            className="w-full sm:w-auto"
            onClick={() => void downloadTemplate()}
            disabled={templateBusy || disabled}
          >
            {templateBusy ? (
              <Loader2 className="animate-spin" aria-hidden="true" />
            ) : (
              <Download aria-hidden="true" />
            )}
            {templateBusy ? 'Şablon hazırlanıyor' : 'Şablonu indir (CSV)'}
          </Button>
          <p className="text-sm text-muted-foreground">
            Şablon ürünlerinizin barkodlarıyla gelir; maliyet sütunlarını doldurun. Doldurulmayan
            satırlar atlanır.
          </p>
        </div>
        {templateError ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-lg bg-loss-soft p-3 text-sm font-medium text-loss"
          >
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>
              <span className="sr-only">Hata: </span>
              {templateError}
            </span>
          </p>
        ) : null}
        {templateTruncated ? (
          <p
            role="note"
            className="flex items-start gap-2 rounded-lg bg-warning-soft p-3 text-sm font-medium text-warning"
          >
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{TEMPLATE_TRUNCATED_NOTE}</span>
          </p>
        ) : null}

        <details className="rounded-md border border-border px-4 py-3">
          <summary className="flex min-h-touch cursor-pointer items-center text-base font-medium">
            Sütunlar ve dosya kuralları
          </summary>
          <div className="flex flex-col gap-3 pb-1 pt-2">
            <ul
              role="list"
              className="flex list-none flex-col gap-1 p-0 text-sm text-muted-foreground"
            >
              <li>
                Biçim: .csv (UTF-8; ayraç ; , veya sekme) ya da .xlsx (yalnız ilk sayfa, ilk satır
                başlık).
              </li>
              <li>
                En çok {Math.floor(IMPORT_MAX_BYTES / (1024 * 1024))} MB ve{' '}
                {IMPORT_MAX_ROWS.toLocaleString('tr-TR')} veri satırı.
              </li>
              <li>
                Aynı barkod ve geçerlilik tarihi dosyada bir kez geçebilir; kayıtlı olanın üstüne
                yazılır.
              </li>
              <li>Sayıda ondalık için virgül yazın; 1.234 gibi belirsiz yazımlar reddedilir.</li>
            </ul>
            <dl className="flex flex-col gap-2 text-sm">
              {TEMPLATE_COLUMNS.map((column) => (
                <div key={column.name} className="flex flex-col">
                  <dt className="flex flex-wrap items-center gap-2 font-medium">
                    <code className="break-all">{column.name}</code>
                    <Badge variant={column.required ? 'warning' : 'neutral'}>
                      {column.required ? 'Zorunlu' : 'İsteğe bağlı'}
                    </Badge>
                  </dt>
                  <dd className="text-muted-foreground">{column.help}</dd>
                </div>
              ))}
            </dl>
          </div>
        </details>

        <div className="flex flex-col gap-2">
          <label htmlFor={inputId} className="text-sm font-medium">
            Maliyet dosyası (.csv veya .xlsx)
          </label>
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={busy}
            aria-invalid={fileError ? true : undefined}
            aria-describedby={fileError ? `${inputId}-hata` : undefined}
            onChange={(e) => void choose(e.target.files?.[0] ?? null)}
            className="min-h-touch w-full rounded-md border border-input-border bg-surface px-3 py-2 text-base file:mr-3 file:rounded-md file:border-0 file:bg-surface-muted file:px-3 file:py-1.5 file:text-base file:font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[invalid=true]:border-2 aria-[invalid=true]:border-loss"
          />
          {fileError ? (
            <p id={`${inputId}-hata`} role="alert" className="text-sm font-medium text-loss">
              <span className="sr-only">Hata: </span>
              {fileError}
            </p>
          ) : null}
        </div>

        {error ? (
          <p
            role="alert"
            className="flex items-start gap-2 rounded-lg bg-loss-soft p-3 text-sm font-medium text-loss"
          >
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>
              <span className="sr-only">Hata: </span>
              {error}
            </span>
          </p>
        ) : null}

        {phase.kind === 'idle' || phase.kind === 'checking' ? (
          <div>
            <Button
              onClick={() => void preview()}
              disabled={!file || busy}
              className="w-full sm:w-auto"
            >
              {phase.kind === 'checking' ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : null}
              {phase.kind === 'checking' ? 'Dosya kontrol ediliyor' : 'Dosyayı kontrol et'}
            </Button>
          </div>
        ) : null}

        {/* Canlı bölge baştan DOM'da: metin sonradan yazılınca ekran okuyucu duyurur (ME-06) */}
        <div role="status" className={report ? undefined : '-mb-4'}>
          {report ? (
            <ReportHeadline report={report} notSaved={phase.kind === 'preview' && phase.notSaved} />
          ) : null}
        </div>
        {report ? (
          <ReportView
            ref={reportRef}
            report={report}
            showAll={showAll}
            onShowAll={() => setShowAll(true)}
          />
        ) : null}

        {phase.kind === 'preview' || phase.kind === 'applying' ? (
          <ApplyActions
            report={phase.report}
            applying={phase.kind === 'applying'}
            onApply={(partial) => void apply(phase.report, partial)}
            onCancel={reset}
          />
        ) : null}
        {phase.kind === 'done' ? (
          <div>
            <Button variant="secondary" onClick={reset}>
              Başka dosya yükle
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ApplyActions({
  report,
  applying,
  onApply,
  onCancel,
}: {
  report: ImportReport;
  applying: boolean;
  onApply: (allowPartial: boolean) => void;
  onCancel: () => void;
}) {
  const spinner = applying ? <Loader2 className="animate-spin" aria-hidden="true" /> : null;
  return (
    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:flex-wrap">
      <Button variant="secondary" onClick={onCancel} disabled={applying}>
        Vazgeç
      </Button>
      {report.valid > 0 && report.invalid === 0 ? (
        <Button onClick={() => onApply(false)} disabled={applying}>
          {spinner}
          {applying ? 'Kaydediliyor' : `${report.valid} satırı kaydet`}
        </Button>
      ) : null}
      {report.valid > 0 && report.invalid > 0 ? (
        <Button onClick={() => onApply(true)} disabled={applying}>
          {spinner}
          {applying ? 'Kaydediliyor' : `Yalnız geçerli ${report.valid} satırı kaydet`}
        </Button>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col rounded-md bg-surface-muted px-3 py-2">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="num text-lg font-semibold">{value.toLocaleString('tr-TR')}</dd>
    </div>
  );
}

function ReportHeadline({ report, notSaved }: { report: ImportReport; notSaved: boolean }) {
  const tone = report.committed ? 'ok' : report.invalid > 0 ? 'warn' : 'ok';
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-lg p-3 text-base font-medium',
        tone === 'ok' ? 'bg-profit-soft text-profit' : 'bg-warning-soft text-warning',
      )}
    >
      {tone === 'ok' ? (
        <CheckCircle2 className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      ) : (
        <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      )}
      <p>
        {report.committed
          ? 'Kaydedildi. '
          : report.dry_run
            ? 'Kontrol tamam, henüz kaydedilmedi. '
            : ''}
        {notSaved ? 'Hatalı satırlar olduğu için hiçbir şey kaydedilmedi. ' : ''}
        {reportHeadline(report)}
      </p>
    </div>
  );
}

const ReportView = forwardRef<
  HTMLElement,
  { report: ImportReport; showAll: boolean; onShowAll: () => void }
>(function ReportView({ report, showAll, onShowAll }, ref) {
  const shown = showAll ? report.errors : report.errors.slice(0, SHOWN_ERRORS);
  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-label="Dosya raporu"
      className="flex flex-col gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Toplam satır" value={report.total} />
        <Stat label="Geçerli" value={report.valid} />
        <Stat label="Hatalı" value={report.invalid} />
        <Stat label="Atlanan (maliyeti boş)" value={report.skipped} />
      </dl>
      {report.unknown_barcodes > 0 ? (
        <p className="text-sm text-muted-foreground">
          <span className="num font-medium">{report.unknown_barcodes}</span> barkod ürün listenizde
          yok. Kayıtları tutulur, ürün senkronlanınca kullanılır.
        </p>
      ) : null}
      {report.ignored_columns.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          Tanınmayan sütunlar yok sayıldı: {report.ignored_columns.join(', ')}.
        </p>
      ) : null}
      {report.valid === 0 && !report.committed ? (
        <p className="text-sm font-medium text-warning">
          Kaydedilecek geçerli satır yok. Dosyayı düzeltip yeniden seçin.
        </p>
      ) : null}
      {report.errors.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-base font-semibold">Satır hataları</h3>
          <ul role="list" aria-label="Satır hataları" className="flex list-none flex-col gap-2 p-0">
            {shown.map((issue, index) => (
              <li
                key={`${issue.row}-${issue.column}-${index}`}
                className="rounded-md border border-border p-3 text-sm"
              >
                <p className="font-medium">
                  <span className="num">Satır {issue.row}</span>
                  {issue.column ? <span>, {columnLabel(issue.column)}</span> : null}
                </p>
                <p>{issue.message || 'Bu satır geçerli değil.'}</p>
                {issue.value ? (
                  <p className="text-muted-foreground">
                    Girilen: <code className="break-all">{issue.value}</code>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
          {!showAll && report.errors.length > SHOWN_ERRORS ? (
            <div>
              <Button variant="secondary" size="sm" onClick={onShowAll}>
                Tüm hataları göster ({report.errors.length})
              </Button>
            </div>
          ) : null}
          {report.errors_truncated ? (
            <p className="text-sm text-muted-foreground">
              Hata listesi ilk {report.errors.length} hatayla sınırlı; düzelttikten sonra dosyayı
              yeniden kontrol edin.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
});
