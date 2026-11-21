"""Senkron yürütücü: backfill ve artımlı çekim (ADR-0005).

Akış (`SyncRunner.run`):

1. `sync_gate.syncable_accounts` ile hesabın kiracısı ve backfill durumu bulunur (kiracı bağlamsız,
   dar işlev). Etkin olmayan hesapta hiçbir şey yapılmaz.
2. Hesap başına PostgreSQL danışma kilidi (advisory lock) alınır; alınamazsa iş çakışmadan çıkar.
3. Kimlik bilgileri YALNIZ worker rolüyle okunup çözülür (`netkar_app` şifreli sütunları okuyamaz).
4. Kaynaklar sırayla işlenir. Her pencere: önce ağdan çekilip bellekte eşlenir (veritabanı işlemi
   yok), sonra TEK işlemde yazılır ve aynı işlemde imleç ve sayaçlar ilerler. Pencere ya tam yazılır
   ya hiç; çökme sonrası yeniden deneme imleçten devam eder, upsert'ler idempotenttir.
5. 401/403: hesap `invalid` yapılır, denetim izi yazılır, senkron durur. Geçici hata (429, 5xx, ağ):
   kaynak başarısız işaretlenir, diğer kaynaklar sürer, iş sonunda yeniden denenir. Kalıcı hata
   (protokol, 4xx, iç hata): kaynak başarısız işaretlenir, iş yeniden denenmez; sonraki planlama
   turu aynı pencereyi imleçten tekrar dener.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from app.core.crypto import DecryptionError
from app.core.envelope import EnvelopeCipher
from app.db.rls import tenant_transaction
from app.integrations.trendyol import TrendyolClient, TrendyolCredentials, TrendyolValidationError
from app.integrations.trendyol.windows import split_window
from app.models import MarketplaceAccount, MarketplaceAccountStatus
from app.profit.constants import CARGO_INVOICE_TEXTS
from app.services.audit import record_audit
from app.services.marketplace_accounts import TrendyolClientFactory, decrypt_credentials
from app.services.sync import mappers, store
from app.services.sync.errors import ErrorInfo, classify_error
from app.services.sync.sources import CARGO_SOURCE, SOURCE_ORDER, SOURCES, SourceSpec

logger = logging.getLogger("netkar.sync")

SyncKind = Literal["backfill", "incremental"]

# Bir çalıştırmada en fazla bu kadar kargo faturasının kalemleri çekilir (kalanı sonraki turda).
CARGO_INVOICES_PER_RUN = 200


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    """Pencere ve geriye bakma kuralları."""

    # Trendyol orders/stream "son 3 ay" der; sınır gününün yorumu belirsiz olduğundan 1 gün pay bırakılır.
    lookback_days: int = 89


@dataclass(slots=True)
class SourceOutcome:
    """Bir kaynağın sonucu (özet; gövde ve ileti yok)."""

    source: str
    status: Literal["succeeded", "failed", "skipped"]
    error_class: str | None = None
    reason: str | None = None
    transient: bool = False
    fetched: int = 0
    upserted: int = 0
    skipped: int = 0
    windows_done: int = 0


@dataclass(slots=True)
class SyncOutcome:
    """Bir senkron çalıştırmasının sonucu."""

    account_id: UUID
    kind: str
    status: Literal["completed", "partial", "invalid", "inactive", "locked", "credentials_error"]
    sources: list[SourceOutcome] = field(default_factory=list)

    @property
    def retryable(self) -> bool:
        """Geçici hata varsa iş geri çekilmeyle yeniden denenmelidir."""
        return any(s.transient for s in self.sources)

    def summary(self) -> dict[str, object]:
        """Görev sonucu olarak saklanacak sayısal özet (kişisel veri ve ileti yok)."""
        return {
            "account_id": str(self.account_id),
            "kind": self.kind,
            "status": self.status,
            "sources": {
                s.source: {"status": s.status, "error_class": s.error_class, "upserted": s.upserted}
                for s in self.sources
            },
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


@asynccontextmanager
async def account_lock(engine: AsyncEngine, account_id: UUID) -> AsyncIterator[bool]:
    """Hesap başına oturum düzeyi danışma kilidi (PostgreSQL advisory lock).

    Süreç çökerse bağlantı kopar ve kilit kendiliğinden düşer. Kilit ayrı bir bağlantıda tutulur;
    senkron işlemleri başka bağlantılarda çalışır. `yield False`: kilit başka bir işte (çakışma yok).
    """
    key = f"netkar:sync:{account_id}"
    conn = await engine.connect()
    acquired = False
    try:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        acquired = bool(
            (
                await conn.execute(text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": key})
            ).scalar()
        )
        yield acquired
    finally:
        try:
            if acquired:
                await conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": key})
        except Exception:
            # Kilit açılamadıysa bağlantı havuza geri dönmesin (kilit oturumla birlikte düşer).
            await conn.invalidate()
        finally:
            await conn.close()


class SyncRunner:
    """Hesap başına senkronu yürütür. Tüm bağımlılıklar dışarıdan verilir (testte sahte taşıma)."""

    def __init__(
        self,
        engine: AsyncEngine,
        client_factory: TrendyolClientFactory,
        envelope: EnvelopeCipher,
        *,
        policy: SyncPolicy | None = None,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._factory = client_factory
        self._envelope = envelope
        self._policy = policy or SyncPolicy()
        self._now = now

    # --- giriş -------------------------------------------------------------------------------

    async def run(
        self,
        account_id: UUID,
        kind: SyncKind,
        *,
        sources: Sequence[str] | None = None,
        force: bool = False,
    ) -> SyncOutcome:
        """Hesabı senkronlar. `sources` None ise tüm kaynaklar; `force` tamamlanmış backfill'i tekrarlar."""
        wanted = [s for s in SOURCE_ORDER if sources is None or s in sources]
        resolved = await self._resolve(account_id)
        if resolved is None:
            return SyncOutcome(account_id, kind, "inactive")
        tenant_id = resolved
        async with account_lock(self._engine, account_id) as acquired:
            if not acquired:
                logger.info("sync atlandı: hesap kilitli", extra={"account_id": str(account_id)})
                return SyncOutcome(account_id, kind, "locked")
            credentials = await self._credentials(tenant_id, account_id)
            if credentials is None:
                return SyncOutcome(account_id, kind, "credentials_error")
            outcome = SyncOutcome(account_id, kind, "completed")
            run_group = uuid.uuid4()
            now = self._now()
            async with self._factory(credentials) as client:
                for name in wanted:
                    source_outcome = await self._run_source(
                        client, name, tenant_id, account_id, run_group, kind, now, force
                    )
                    outcome.sources.append(source_outcome)
                    if source_outcome.status == "failed" and source_outcome.error_class in (
                        "unauthorized",
                        "forbidden",
                    ):
                        await self._invalidate(tenant_id, account_id, source_outcome)
                        outcome.status = "invalid"
                        return outcome
            if any(s.status == "failed" for s in outcome.sources):
                outcome.status = "partial"
            return outcome

    # --- hesap ve kimlik bilgisi ----------------------------------------------------------------

    async def _resolve(self, account_id: UUID) -> UUID | None:
        """Hesabın kiracısı (yalnız etkin hesaplar). Kiracı bağlamı gerekmez: dar SECURITY DEFINER işlevi."""
        async with self._sessions() as session:
            row = (
                await session.execute(
                    text("SELECT tenant_id FROM sync_gate.syncable_accounts(:id)"), {"id": account_id}
                )
            ).first()
            await session.rollback()
        return None if row is None else UUID(str(row[0]))

    async def _credentials(self, tenant_id: UUID, account_id: UUID) -> TrendyolCredentials | None:
        """Şifreli anahtarları okur ve çözer. Hata ayrıntısı loga yazılmaz (yalnız sınıf)."""
        async with tenant_transaction(self._sessions, tenant_id) as session:
            account = (
                await session.execute(
                    select(MarketplaceAccount)
                    .options(
                        undefer(MarketplaceAccount.api_key_encrypted),
                        undefer(MarketplaceAccount.api_secret_encrypted),
                    )
                    .where(
                        MarketplaceAccount.id == account_id,
                        MarketplaceAccount.tenant_id == tenant_id,
                        MarketplaceAccount.status == MarketplaceAccountStatus.ACTIVE.value,
                    )
                )
            ).scalar_one_or_none()
        if account is None:
            return None
        try:
            return decrypt_credentials(self._envelope, account)
        except (DecryptionError, ValueError) as exc:
            logger.error(
                "sync: kimlik bilgisi çözülemedi",
                extra={"account_id": str(account_id), "error_class": type(exc).__name__},
            )
            return None

    async def _invalidate(self, tenant_id: UUID, account_id: UUID, failed: SourceOutcome) -> None:
        """401/403: hesabı `invalid` yapar ve denetim izine yazar (yalnız neden kodu ve kaynak)."""
        async with tenant_transaction(self._sessions, tenant_id) as session:
            result = await session.execute(
                update(MarketplaceAccount)
                .where(
                    MarketplaceAccount.id == account_id,
                    MarketplaceAccount.tenant_id == tenant_id,
                    MarketplaceAccount.status == MarketplaceAccountStatus.ACTIVE.value,
                )
                .values(status=MarketplaceAccountStatus.INVALID.value, updated_at=func.now())
                .execution_options(synchronize_session=False)
            )
            if result.rowcount:  # type: ignore[attr-defined]
                await record_audit(
                    session,
                    tenant_id,
                    "marketplace_account.sync_invalidated",
                    target=str(account_id),
                    meta={"reason": failed.error_class, "source": failed.source},
                )
        logger.warning(
            "sync: hesap geçersiz işaretlendi",
            extra={"account_id": str(account_id), "reason": failed.error_class, "source": failed.source},
        )

    # --- kaynak adımı -----------------------------------------------------------------------------

    async def _run_source(
        self,
        client: TrendyolClient,
        name: str,
        tenant_id: UUID,
        account_id: UUID,
        run_group: UUID,
        kind: SyncKind,
        now: datetime,
        force: bool,
    ) -> SourceOutcome:
        async with tenant_transaction(self._sessions, tenant_id) as session:
            cursor = await store.load_cursor(session, account_id, name)
        backfilled = cursor is not None and cursor.backfill_completed_at is not None
        if kind == "incremental" and not backfilled:
            return SourceOutcome(name, "skipped", reason="needs_backfill")
        if kind == "backfill" and backfilled and not force:
            return SourceOutcome(name, "skipped", reason="already_backfilled")
        if name == CARGO_SOURCE:
            return await self._run_cargo(client, tenant_id, account_id, run_group, kind, now)
        spec = SOURCES[name]
        watermark = cursor.watermark if cursor is not None else None
        windows = self._windows(spec, kind, now, watermark, force)
        return await self._run_windows(client, spec, tenant_id, account_id, run_group, kind, now, windows)

    def _windows(
        self,
        spec: SourceSpec,
        kind: SyncKind,
        now: datetime,
        watermark: datetime | None,
        force: bool,
    ) -> list[tuple[datetime, datetime]]:
        """Çekilecek pencereler. `span` None ise tek (tarihsiz) pencere: tam yenileme."""
        if spec.span is None:
            return [(now, now)]
        horizon = now - timedelta(days=self._policy.lookback_days)
        if kind == "backfill":
            # Yarım kalan backfill imleçten devam eder; `force` baştan başlar.
            start = horizon if (force or watermark is None) else max(horizon, watermark)
        else:
            assert watermark is not None  # incremental yalnız backfill sonrası çalışır
            start = max(horizon, watermark - spec.overlap)
        if start >= now:
            return []
        return split_window(start, now, spec.span)

    async def _run_windows(
        self,
        client: TrendyolClient,
        spec: SourceSpec,
        tenant_id: UUID,
        account_id: UUID,
        run_group: UUID,
        kind: SyncKind,
        now: datetime,
        windows: list[tuple[datetime, datetime]],
    ) -> SourceOutcome:
        dated = spec.span is not None
        async with tenant_transaction(self._sessions, tenant_id) as session:
            run_id = await store.start_run(
                session,
                tenant_id=tenant_id,
                account_id=account_id,
                run_group_id=run_group,
                kind=kind,
                source=spec.name,
                window_start=windows[0][0] if dated and windows else None,
                window_end=windows[-1][1] if dated and windows else None,
                windows_total=len(windows),
            )
        outcome = SourceOutcome(spec.name, "succeeded")
        for window_start, window_end in windows:
            try:
                batch = await spec.fetch(client, window_start, window_end)
                async with tenant_transaction(self._sessions, tenant_id) as session:
                    upserted = await spec.write(session, tenant_id, account_id, batch.rows)
                    await store.bump_run(
                        session, run_id, fetched=batch.fetched, upserted=upserted, skipped=batch.skipped
                    )
                    await store.advance_cursor(
                        session,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        source=spec.name,
                        watermark=window_end,
                        window_start=window_start if dated else None,
                    )
            except Exception as exc:
                return await self._fail(tenant_id, run_id, outcome, exc)
            outcome.fetched += batch.fetched
            outcome.upserted += upserted
            outcome.skipped += batch.skipped
            outcome.windows_done += 1
        async with tenant_transaction(self._sessions, tenant_id) as session:
            await self._complete(session, tenant_id, account_id, spec.name, kind, now, run_id)
        return outcome

    async def _complete(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        account_id: UUID,
        source: str,
        kind: SyncKind,
        now: datetime,
        run_id: UUID,
    ) -> None:
        """Kaynağı tamamlar: çalışma kaydını kapatır; backfill ise tamamlanma zamanını işler."""
        await store.finish_run(session, run_id, status="succeeded")
        # Pencere yoksa (ör. products) imleç hâlâ yazılmamış olabilir: watermark en az `now` olur.
        await store.advance_cursor(
            session,
            tenant_id=tenant_id,
            account_id=account_id,
            source=source,
            watermark=now,
            window_start=None,
            backfill_completed_at=now if kind == "backfill" else None,
        )

    async def _fail(
        self, tenant_id: UUID, run_id: UUID, outcome: SourceOutcome, exc: BaseException
    ) -> SourceOutcome:
        """Pencere hatası: çalışma kaydı `failed` + hata SINIFI. İleti ve gövde hiçbir yere yazılmaz."""
        info: ErrorInfo = classify_error(exc)
        async with tenant_transaction(self._sessions, tenant_id) as session:
            await store.finish_run(session, run_id, status="failed", error_class=info.error_class)
        logger.warning(
            "sync: kaynak adımı başarısız",
            extra={"source": outcome.source, "error_class": info.error_class, "transient": info.transient},
        )
        outcome.status = "failed"
        outcome.error_class = info.error_class
        outcome.transient = info.transient
        return outcome

    # --- kargo faturaları ---------------------------------------------------------------------------

    async def _run_cargo(
        self,
        client: TrendyolClient,
        tenant_id: UUID,
        account_id: UUID,
        run_group: UUID,
        kind: SyncKind,
        now: datetime,
    ) -> SourceOutcome:
        """Kargo faturası kalemleri: ekstredeki "Kargo Faturası" satırlarının seri numaralarından."""
        async with tenant_transaction(self._sessions, tenant_id) as session:
            serials = [
                str(r[0])
                for r in (
                    await session.execute(
                        text(
                            "SELECT DISTINCT f.transaction_id FROM financial_transactions f "
                            "WHERE f.marketplace_account_id = :a AND f.source = 'other_financials' "
                            "AND f.request_type = 'DeductionInvoices' AND f.type_text = ANY(:texts) "
                            "AND NOT EXISTS (SELECT 1 FROM cargo_invoice_items c "
                            "WHERE c.marketplace_account_id = f.marketplace_account_id "
                            "AND c.invoice_serial_number = f.transaction_id) "
                            "ORDER BY f.transaction_id LIMIT :n"
                        ),
                        {"a": account_id, "texts": sorted(CARGO_INVOICE_TEXTS), "n": CARGO_INVOICES_PER_RUN},
                    )
                ).all()
            ]
            run_id = await store.start_run(
                session,
                tenant_id=tenant_id,
                account_id=account_id,
                run_group_id=run_group,
                kind=kind,
                source="cargo_invoices",
                window_start=None,
                window_end=None,
                windows_total=len(serials),
            )
        outcome = SourceOutcome("cargo_invoices", "succeeded")
        for serial in serials:
            try:
                items = [item async for item in client.iter_cargo_invoice_items(serial)]
                rows, skipped = mappers.map_cargo_items(serial, items)
                async with tenant_transaction(self._sessions, tenant_id) as session:
                    upserted = await store.upsert_cargo_items(
                        session, rows, tenant_id=tenant_id, account_id=account_id
                    )
                    await store.bump_run(
                        session, run_id, fetched=len(items), upserted=upserted, skipped=skipped
                    )
            except Exception as exc:
                if isinstance(exc, TrendyolValidationError):
                    # Geçersiz seri numarası: yalnız o fatura atlanır, kaynak sürer.
                    outcome.skipped += 1
                    continue
                return await self._fail(tenant_id, run_id, outcome, exc)
            outcome.fetched += len(items)
            outcome.upserted += upserted
            outcome.skipped += skipped
            outcome.windows_done += 1
        async with tenant_transaction(self._sessions, tenant_id) as session:
            await self._complete(session, tenant_id, account_id, "cargo_invoices", kind, now, run_id)
        return outcome
