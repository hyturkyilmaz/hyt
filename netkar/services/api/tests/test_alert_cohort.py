"""İade kohort sorgusu (ADR-0009 D3): gerçek PostgreSQL, RLS'li uygulama rolü, elle hesaplanmış beklentiler.

Değerlendirme günü T = 2026-12-01 (İstanbul). `cohort_windows` ile (H=21):
  güncel kohort sipariş günü [2026-10-13, 2026-11-10), taban kohort [2026-07-21, 2026-10-13), İstanbul günü.
UTC karşılığı (UTC+3): güncel [2026-10-12T21:00Z, 2026-11-09T21:00Z), taban [2026-07-20T21:00Z, 2026-10-12T21:00Z).

Dosya adı bilerek `test_alerts_*` değildir: `make test-alerts` (DB'siz, saf kural kapsamı) bunu toplamaz.
Sorgu `app/services/alert_inputs.py` içindedir (app/alerts saf kalır).
"""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts import AlertThresholds, RuleStatus, evaluate_return_rate
from app.alerts.stats import cohort_windows
from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.services.alert_inputs import (
    COUNTED_RETURN_STATUSES,
    AccountReturnCounts,
    ReturnCohortSet,
    TenantContextMismatch,
    istanbul_day_start,
    load_return_cohorts,
)
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller, make_seller
from tests.trendyol_helpers import load_fixture

T = date(2026, 12, 1)
ACCEPTED = "Accepted"
_ids = itertools.count(1000)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture
async def sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def seller(admin_conn: psycopg.Connection[Any]) -> Seller:
    return make_seller(admin_conn)


def add_line(
    conn: psycopg.Connection[Any],
    seller: Seller,
    ordered: str,
    barcode: str,
    *,
    order_status: str = "Delivered",
    line_status: str | None = None,
    removed: bool = False,
    claims: tuple[tuple[str | None, str | None, str | None], ...] = (),
    claim_keys: str = "line",
    order_no: str | None = None,
    package: int | None = None,
    line_id: int | None = None,
    modified: str | None = None,
    item_id: str | None = None,
) -> str:
    """Satır ekler (aynı `package` varsa mevcut siparişe). `claims`: (statü, claim_date, neden kodu) kalemleri.

    `claim_keys`: "line" iadede yalnız `order_line_id`, "item" yalnız `order_line_item_id` (satırın kalem
    kimliği `ITEM<line_id>`) dolu olur. Dönen: sipariş numarası.
    """
    order_no = order_no or f"N{next(_ids)}"
    package = package or next(_ids)
    line_id = line_id or next(_ids)
    existing = conn.execute(
        "SELECT id FROM orders WHERE marketplace_account_id = %s AND shipment_package_id = %s",
        (seller.account_id, package),
    ).fetchone()
    if existing is None:
        existing = conn.execute(
            "INSERT INTO orders (tenant_id, marketplace_account_id, order_number, shipment_package_id, "
            "ordered_at, status, last_modified_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                seller.tenant_id,
                seller.account_id,
                order_no,
                package,
                utc(ordered),
                order_status,
                None if modified is None else utc(modified),
            ),
        ).fetchone()
    assert existing is not None
    items = json.dumps([{"id": item_id or f"ITEM{line_id}", "seller_discount": "0", "ty_discount": "0"}])
    conn.execute(
        "INSERT INTO order_lines (tenant_id, marketplace_account_id, order_id, line_id, barcode, quantity, "
        "line_gross_amount, status, removed_at, items) VALUES (%s, %s, %s, %s, %s, 1, 100, %s, %s, %s)",
        (
            seller.tenant_id,
            seller.account_id,
            existing[0],
            line_id,
            barcode,
            line_status,
            utc("2026-11-20T00:00:00") if removed else None,
            items,
        ),
    )
    for status, claim_date, reason in claims:
        add_return(
            conn,
            seller,
            order_no,
            status,
            claim_date,
            reason,
            line_id=line_id if claim_keys == "line" else None,
            item_id=(item_id or f"ITEM{line_id}") if claim_keys == "item" else None,
            barcode=barcode,
        )
    return order_no


def add_return(
    conn: psycopg.Connection[Any],
    seller: Seller,
    order_no: str | None,
    status: str | None,
    claim_date: str | None,
    reason: str | None = None,
    *,
    line_id: int | None = None,
    item_id: str | None = None,
    barcode: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO returns (tenant_id, marketplace_account_id, claim_id, claim_item_id, order_number, "
        "order_line_id, order_line_item_id, barcode, reason_code, status, claim_date) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            seller.tenant_id,
            seller.account_id,
            f"C{next(_ids)}",
            f"I{next(_ids)}",
            order_no,
            line_id,
            item_id,
            barcode,
            reason,
            status,
            None if claim_date is None else utc(claim_date),
        ),
    )


def after(ordered: str, **delta: float) -> str:
    return (utc(ordered) + timedelta(**delta)).replace(tzinfo=None).isoformat()


async def load(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, account_id: UUID | None = None
) -> ReturnCohortSet:
    async with tenant_transaction(sessions, seller.tenant_id) as session:
        return await load_return_cohorts(session, seller.tenant_id, account_id or seller.account_id, T)


def by_barcode(result: ReturnCohortSet) -> dict[str, tuple[int, int, int, int]]:
    return {
        c.barcode: (c.current_lines, c.current_returned, c.base_lines, c.base_returned)
        for c in result.products
    }


def test_windows_and_constants_match_the_hand_calculation() -> None:
    assert cohort_windows(T) == (
        date(2026, 10, 13),
        date(2026, 11, 10),
        date(2026, 7, 21),
        date(2026, 10, 13),
    )
    assert istanbul_day_start(date(2026, 10, 13)) == utc("2026-10-12T21:00:00")
    assert COUNTED_RETURN_STATUSES == (ACCEPTED,)


async def test_window_edges_are_half_open_on_istanbul_days(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    claim = lambda ordered: ((ACCEPTED, after(ordered, days=1), None),)  # noqa: E731
    cases = {
        "2026-10-12T20:59:59": "base",  # İstanbul 10-12 23:59:59
        "2026-10-12T21:00:00": "current",  # İstanbul 10-13 00:00:00
        "2026-11-09T20:59:59": "current",  # İstanbul 11-09 23:59:59
        "2026-11-09T21:00:00": "out",  # İstanbul 11-10 00:00:00: üst uç dışarıda
        "2026-07-20T21:00:00": "base",  # İstanbul 07-21 00:00:00: alt uç içeride
        "2026-07-20T20:59:59": "out",  # İstanbul 07-20 23:59:59
    }
    for ordered in cases:
        add_line(admin_conn, seller, ordered, "EDGE", claims=claim(ordered))
    # Gün sınırı dışındaki "geç saat" (UTC günü ile İstanbul günü farkı): 23:50 UTC = ertesi gün 02:50 İstanbul.
    add_line(
        admin_conn, seller, "2026-11-08T23:50:00", "EDGE", claims=claim("2026-11-08T23:50:00")
    )  # current
    add_line(admin_conn, seller, "2026-10-12T23:50:00", "EDGE")  # İstanbul 10-13 02:50 -> current, iadesiz
    result = await load(sessions, seller)
    assert by_barcode(result) == {"EDGE": (4, 3, 2, 2)}
    assert sum(1 for v in cases.values() if v == "current") == 2  # el sayımı: 2 + 2 geç saat = 4 güncel


async def test_counts_horizon_cancellation_status_and_reasons_by_hand(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    def a(ordered: str, **kw: Any) -> None:
        add_line(admin_conn, seller, ordered, "A", **kw)

    # --- A, güncel kohort
    o1 = "2026-10-20T10:00:00"
    a(
        o1, claims=((ACCEPTED, after(o1, days=5), "R1"), (ACCEPTED, after(o1, days=6), "R4"))
    )  # x (iki kalem, tek sayılır)
    o2 = "2026-10-21T10:00:00"
    a(o2, claims=((ACCEPTED, after(o2, days=21), "R2"),))  # tam ufukta: x (<=)
    o3 = "2026-10-22T10:00:00"
    a(o3, claims=((ACCEPTED, after(o3, days=21, seconds=1), "R9"),))  # ufku 1 sn aşar: x değil
    o4 = "2026-10-23T10:00:00"
    a(o4, claims=(("Rejected", after(o4, days=2), "R8"),))  # statü Accepted değil
    a("2026-10-24T10:00:00")  # iadesiz
    o6 = "2026-10-25T10:00:00"
    a(o6, claims=((ACCEPTED, after(o6, days=1), "R1"), (ACCEPTED, after(o6, days=2), "R3")))  # x
    o7 = "2026-10-26T10:00:00"
    a(o7, order_status="Cancelled", claims=((ACCEPTED, after(o7, days=1), "R7"),))  # iptal sipariş: dışarıda
    o8 = "2026-10-27T10:00:00"
    a(o8, line_status="UnSupplied", claims=((ACCEPTED, after(o8, days=1), "R7"),))  # iptal satır: dışarıda
    o9 = "2026-10-28T10:00:00"
    a(o9, removed=True, claims=((ACCEPTED, after(o9, days=1), "R7"),))  # silinmiş satır: dışarıda
    o10 = "2026-10-29T10:00:00"
    a(o10, claims=((None, after(o10, days=1), "R6"),))  # statüsüz: sayılmaz
    o11 = "2026-10-30T10:00:00"
    a(o11, claims=((ACCEPTED, None, "R5"),))  # claim_date yok: sayılmaz
    # --- A, taban kohort (ufuk burada da uygulanır)
    b1 = "2026-08-01T10:00:00"
    a(b1, claims=((ACCEPTED, after(b1, days=3), "RB"),))  # x
    b2 = "2026-09-01T10:00:00"
    a(b2, claims=((ACCEPTED, after(b2, days=22), "RB"),))  # ufku aşar: x değil
    a("2026-09-10T10:00:00")
    # --- B: iadesiz güncel 2, taban 1 iadeli
    add_line(admin_conn, seller, "2026-11-01T10:00:00", "B")
    add_line(admin_conn, seller, "2026-11-02T10:00:00", "B")
    bb = "2026-09-20T10:00:00"
    add_line(admin_conn, seller, bb, "B", claims=((ACCEPTED, after(bb, days=4), "RB"),))
    # --- C: yalnız taban, iade claim_date'siz
    add_line(admin_conn, seller, "2026-09-21T10:00:00", "C", claims=((ACCEPTED, None, None),))

    result = await load(sessions, seller)

    # A güncel: o1,o2,o3,o4,24.,o6,o10,o11 = 8 satır; x = o1,o2,o6 = 3. A taban: 3 satır, x = 1.
    assert by_barcode(result) == {"A": (8, 3, 3, 1), "B": (2, 0, 1, 1), "C": (0, 0, 1, 0)}
    assert [c.barcode for c in result.products] == ["A", "B", "C"]
    # Neden kodları: yalnız güncel kohortta sayılan iadeler. R1:2 (o1,o6), R2:1, R3:1, R4:1 -> ilk 3, eşitlikte ada göre.
    cohort_a = next(c for c in result.products if c.barcode == "A")
    assert cohort_a.reason_codes == ("R1", "R2", "R3")
    assert next(c for c in result.products if c.barcode == "B").reason_codes == ()
    # Hesap toplamı ürünlerin toplamıdır (A+B+C): güncel 10 / 3, taban 5 / 2.
    assert result.account == AccountReturnCounts(
        current_lines=10, current_returned=3, base_lines=5, base_returned=2
    )
    assert result.account.current_lines == sum(c.current_lines for c in result.products)
    assert result.account.current_returned == sum(c.current_returned for c in result.products)
    assert result.account.base_lines == sum(c.base_lines for c in result.products)
    assert result.account.base_returned == sum(c.base_returned for c in result.products)


async def test_empty_windows_return_nothing_and_zero_account_totals(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    assert await load(sessions, seller) == ReturnCohortSet(
        products=(),
        account=AccountReturnCounts(current_lines=0, current_returned=0, base_lines=0, base_returned=0),
    )
    # Pencere dışında kalan satır da boş sonuç verir (ufuk dışı bir iade sayıma girmez).
    add_line(
        admin_conn, seller, "2026-11-20T10:00:00", "X", claims=((ACCEPTED, "2026-11-21T10:00:00", None),)
    )
    assert (await load(sessions, seller)).products == ()


async def test_tenant_isolation_other_tenant_rows_are_never_counted(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    other = make_seller(admin_conn, seller_id="2739")
    o = "2026-10-20T10:00:00"
    add_line(admin_conn, seller, o, "A", claims=((ACCEPTED, after(o, days=1), "R1"),))
    for _ in range(3):  # başka kiracı: aynı barkod, çok sayıda satır ve iade
        add_line(admin_conn, other, o, "A", claims=((ACCEPTED, after(o, days=1), "R2"),))
    mine = await load(sessions, seller)
    assert by_barcode(mine) == {"A": (1, 1, 0, 0)} and mine.products[0].reason_codes == ("R1",)
    theirs = await load(sessions, other)
    assert by_barcode(theirs) == {"A": (3, 3, 0, 0)} and theirs.products[0].reason_codes == ("R2",)
    # Kendi bağlamım, başkasının hesap kimliği: hiçbir satır dönmez (RLS + açık tenant süzgeci).
    foreign = await load(sessions, seller, account_id=other.account_id)
    assert foreign.products == () and foreign.account.current_lines == 0


async def test_end_to_end_with_the_return_rate_rule(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    # HOT: güncel 50 satır / 15 iade (%30), taban 100 satır / 5 iade (%5); CALM: iadesiz (örneklem eşiği için
    # n*p >= 5 koşulu HOT için havuzlu p = 20/150 ile sağlanır).
    for i in range(50):
        ordered = f"2026-10-{14 + i % 10:02d}T10:00:00"
        claims = ((ACCEPTED, after(ordered, days=3), "DEFECT" if i % 2 else "SIZE"),) if i < 15 else ()
        add_line(admin_conn, seller, ordered, "HOT", claims=claims)
    for i in range(100):
        ordered = f"2026-08-{1 + i % 28:02d}T10:00:00"
        claims = ((ACCEPTED, after(ordered, days=3), "SIZE"),) if i < 5 else ()
        add_line(admin_conn, seller, ordered, "HOT", claims=claims)
    for i in range(50):
        ordered = f"2026-10-{14 + i % 10:02d}T10:00:00"
        add_line(admin_conn, seller, ordered, "CALM")
    for i in range(100):
        ordered = f"2026-08-{1 + i % 28:02d}T10:00:00"
        add_line(admin_conn, seller, ordered, "CALM")

    cohorts = await load(sessions, seller)
    assert by_barcode(cohorts) == {"CALM": (50, 0, 100, 0), "HOT": (50, 15, 100, 5)}
    assert cohorts.account == AccountReturnCounts(
        current_lines=100, current_returned=15, base_lines=200, base_returned=5
    )

    outcome = evaluate_return_rate(seller.account_id, T, cohorts.products, AlertThresholds())
    assert outcome.status is RuleStatus.EVALUATED
    subjects = {c.subject for c in outcome.candidates}
    assert subjects == {"urun:HOT", "hesap:*"}
    hot = next(c for c in outcome.candidates if c.subject == "urun:HOT")
    assert hot.evidence["current_lines"] == 50 and hot.evidence["current_returned"] == 15
    assert hot.evidence["base_lines"] == 100 and hot.evidence["base_returned"] == 5
    assert hot.evidence["reason_codes"] == "SIZE,DEFECT"  # i=0..14: SIZE 8, DEFECT 7
    assert Decimal(str(hot.evidence["current_rate_percent"])) == Decimal("30.00")


async def test_split_package_counts_the_logical_line_once(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    o = "2026-10-20T10:00:00"
    # Paket 1 UnPacked (eski, SON değişen), paket 2 Delivered; aynı sipariş numarası ve lineId; tek iade.
    add_line(
        admin_conn,
        seller,
        o,
        "S",
        order_status="UnPacked",
        order_no="SPLIT",
        line_id=77,
        modified="2026-10-25T00:00:00",
    )
    add_line(
        admin_conn, seller, o, "S", order_no="SPLIT", line_id=77, modified="2026-10-21T00:00:00",
        claims=((ACCEPTED, after(o, days=2), "R1"), (ACCEPTED, after(o, days=3), "R1")),
    )  # fmt: skip
    result = await load(sessions, seller)
    assert by_barcode(result) == {"S": (1, 1, 0, 0)}
    assert result.products[0].reason_codes == ("R1",)
    assert result.account == AccountReturnCounts(
        current_lines=1, current_returned=1, base_lines=0, base_returned=0
    )
    # Yeni paket henüz senkronlanmamışsa (yalnız UnPacked kaldı) mantıksal satır sayılmaz.
    add_line(admin_conn, seller, o, "S2", order_status="UnPacked", order_no="SPLIT2", line_id=78)
    assert by_barcode(await load(sessions, seller)) == {"S": (1, 1, 0, 0)}


async def test_reason_codes_count_once_per_line(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    o = "2026-10-20T10:00:00"
    add_line(
        admin_conn, seller, o, "A", claims=((ACCEPTED, after(o, days=1), "R1"),) * 3
    )  # tek satır, 3 kalem
    for _ in range(2):
        add_line(admin_conn, seller, o, "A", claims=((ACCEPTED, after(o, days=1), "R2"),))
    result = await load(sessions, seller)
    assert result.products[0].reason_codes == ("R2", "R1")  # R2: 2 satır, R1: 1 satır (3 kalem değil)


async def test_two_line_order_with_one_returned_line(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    o = "2026-10-20T10:00:00"
    add_line(
        admin_conn, seller, o, "A", order_no="TWO", package=555, claims=((ACCEPTED, after(o, days=2), "R1"),)
    )
    add_line(admin_conn, seller, o, "A", order_no="TWO", package=555)
    assert by_barcode(await load(sessions, seller)) == {"A": (2, 1, 0, 0)}


async def test_item_key_and_line_key_both_link_returns_to_lines(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    o = "2026-10-20T10:00:00"
    add_line(admin_conn, seller, o, "A", claims=((ACCEPTED, after(o, days=1), None),), claim_keys="item")
    add_line(admin_conn, seller, o, "A", claims=((ACCEPTED, after(o, days=1), None),), claim_keys="line")
    result = await load(sessions, seller)
    assert by_barcode(result) == {"A": (2, 2, 0, 0)}
    assert result.unmatched_returns == 0 and result.orphan_returns == 0


async def test_unmatched_and_orphan_returns_are_counted_per_account(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    other = make_seller(admin_conn, seller_id="2739")
    d = "2026-10-20T10:00:00"
    add_line(admin_conn, seller, d, "A", order_no="K1", line_id=5, claims=((ACCEPTED, d, None),))  # bağlı
    # İptal ve silinmiş satırın iadesi yetim DEĞİL (satır hesapta var, yalnız kohortta sayılmaz).
    add_line(
        admin_conn,
        seller,
        d,
        "A",
        order_no="K2",
        line_id=6,
        order_status="Cancelled",
        claims=((ACCEPTED, d, None),),
    )
    add_line(
        admin_conn, seller, d, "A", order_no="K3", line_id=7, removed=True, claims=((ACCEPTED, d, None),)
    )
    # Bağlanamayanlar (anahtar eksik): claim_date, order_number, her iki satır anahtarı.
    add_return(admin_conn, seller, "K1", ACCEPTED, None, line_id=5)
    add_return(admin_conn, seller, None, ACCEPTED, d, line_id=5)
    add_return(admin_conn, seller, "K1", ACCEPTED, d)
    # Yetimler: anahtarlar dolu ama karşılık yok (yanlış sipariş numarası, yanlış satır, yanlış kalem kimliği).
    add_return(admin_conn, seller, "YOK", ACCEPTED, d, line_id=5)
    add_return(admin_conn, seller, "K1", ACCEPTED, d, line_id=999)
    add_return(admin_conn, seller, "K1", ACCEPTED, d, item_id="ITEM999")
    # Sayılmayan statü ve başka hesap (aynı kiracı): hiçbirine girmez.
    add_return(admin_conn, seller, "YOK", "Rejected", d, line_id=5)
    add_return(admin_conn, other, "YOK", ACCEPTED, None)
    result = await load(sessions, seller)
    assert (result.unmatched_returns, result.orphan_returns) == (3, 3)
    assert by_barcode(result) == {"A": (1, 1, 0, 0)}
    theirs = await load(sessions, other)
    assert (theirs.unmatched_returns, theirs.orphan_returns) == (1, 0)


async def test_second_account_of_the_same_tenant_is_isolated(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    account2 = uuid4()
    admin_conn.execute(
        "INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, created_by, "
        "api_key_last4, revoked_at) VALUES (%s, %s, 'trendyol', '2740', 'revoked', %s, 'xxxx', now())",
        (account2, seller.tenant_id, seller.user_id),
    )
    second = Seller(seller.tenant_id, seller.user_id, account2, "2740")
    o = "2026-10-20T10:00:00"
    add_line(
        admin_conn, seller, o, "A", order_no="SAME", line_id=1, claims=((ACCEPTED, after(o, days=1), "R1"),)
    )
    for line in (1, 2):  # aynı sipariş numarası ve line_id=1 (seller'da da var): hesap sınırı ayırır
        add_line(
            admin_conn, second, o, "A", order_no="SAME", line_id=line,
            claims=((ACCEPTED, after(o, days=1), "R2"),),
        )  # fmt: skip
    assert by_barcode(await load(sessions, seller)) == {"A": (1, 1, 0, 0)}
    both = await load(sessions, seller, account_id=account2)
    assert by_barcode(both) == {"A": (2, 2, 0, 0)} and both.products[0].reason_codes == ("R2",)


async def test_foreign_tenant_context_is_rejected(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    other = make_seller(admin_conn, seller_id="2739")
    async with tenant_transaction(sessions, seller.tenant_id) as session:
        with pytest.raises(TenantContextMismatch):
            await load_return_cohorts(session, other.tenant_id, other.account_id, T)
        # Aynı kiracı bağlamı (zaten kurulu) sorunsuz; bağlamsız oturum da kendi bağlamını kurar.
        await load_return_cohorts(session, seller.tenant_id, seller.account_id, T)
    async with sessions() as bare, bare.begin():
        await load_return_cohorts(bare, other.tenant_id, other.account_id, T)


def test_claims_and_shipment_fixtures_do_not_meet_on_any_key() -> None:
    """Fixture'lar aynı satırda BULUŞMAZ: claim `orderLine.id` = shipment `lineId` varsayımı doğrulanamaz.

    Claim fixture'ı sipariş 65745805, orderLine.id 28717254, orderLineItemId 29815493; shipment fixture'ı
    siparişler 10654411111/2, lineId 4765111111, lineItemId 11111111/2. Bu test eşitliği ZORLAMAZ, yalnız mevcut
    durumu sabitler: fixture'lar hizalanırsa test kırılır ve (b) yolu bu fixture'larla doğrulanabilir hale gelir.
    """
    claims = load_fixture("claims.json")["content"]
    packages = load_fixture("shipment_packages_v2.json")["content"]
    orders = {p["orderNumber"] for p in packages}
    line_ids = {str(line["lineId"]) for p in packages for line in p["lines"]}
    item_ids = {
        str(d["lineItemId"]) for p in packages for line in p["lines"] for d in line["discountDetails"]
    }
    for claim in claims:
        assert claim["orderNumber"] not in orders
        for item in claim["items"]:
            assert str(item["orderLine"]["id"]) not in line_ids
            for ci in item["claimItems"]:
                assert str(ci["orderLineItemId"]) not in item_ids


async def test_item_key_takes_priority_over_line_id_and_ambiguity_is_counted(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    d = "2026-10-20T10:00:00"
    add_line(admin_conn, seller, d, "A", order_no="PR", package=900, line_id=11)
    add_line(admin_conn, seller, d, "A", order_no="PR", package=900, line_id=12)
    # order_line_id satır 11'i, kalem kimliği satır 12'yi gösterir: yalnız kalem anahtarı (satır 12) geçerli.
    add_return(admin_conn, seller, "PR", ACCEPTED, after(d, days=1), line_id=11, item_id="ITEM12")
    result = await load(sessions, seller)
    assert by_barcode(result) == {"A": (2, 1, 0, 0)} and result.ambiguous_returns == 0
    # Aynı kalem kimliği iki mantıksal satırda: belirsiz sayılır (iki satıra da bağlanır).
    add_line(admin_conn, seller, d, "B", order_no="AM", package=901, line_id=21, item_id="SHARED")
    add_line(admin_conn, seller, d, "B", order_no="AM", package=901, line_id=22, item_id="SHARED")
    add_return(admin_conn, seller, "AM", ACCEPTED, after(d, days=1), item_id="SHARED")
    result = await load(sessions, seller)
    assert by_barcode(result) == {"A": (2, 1, 0, 0), "B": (2, 2, 0, 0)}
    assert result.ambiguous_returns == 1 and result.orphan_returns == 0


async def test_split_package_is_not_ambiguous_and_old_package_item_ids_still_link(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    d = "2026-10-20T10:00:00"
    # Aynı mantıksal satır iki pakette; kalem kimlikleri eski pakette (seçilmeyen kayıt) kalmış.
    add_line(
        admin_conn,
        seller,
        d,
        "S",
        order_no="SP",
        package=910,
        line_id=31,
        item_id="OLD",
        order_status="UnPacked",
    )
    add_line(
        admin_conn,
        seller,
        d,
        "S",
        order_no="SP",
        package=911,
        line_id=31,
        item_id="NEW",
        modified="2026-10-22T00:00:00",
    )
    add_return(admin_conn, seller, "SP", ACCEPTED, after(d, days=1), item_id="OLD")
    result = await load(sessions, seller)
    assert by_barcode(result) == {"S": (1, 1, 0, 0)}
    assert (result.unmatched_returns, result.orphan_returns, result.ambiguous_returns) == (0, 0, 0)


async def test_cancelled_newer_package_does_not_hide_a_live_older_record(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    d = "2026-10-20T10:00:00"
    add_line(admin_conn, seller, d, "C", order_no="CN", package=920, line_id=41, modified="2026-10-21T00:00:00",
             claims=((ACCEPTED, after(d, days=2), "R1"),))  # fmt: skip
    add_line(admin_conn, seller, d, "C", order_no="CN", package=921, line_id=41, order_status="Cancelled",
             modified="2026-10-25T00:00:00")  # fmt: skip
    assert by_barcode(await load(sessions, seller)) == {"C": (1, 1, 0, 0)}
    # Tüm kayıtlar iptalse satır düşer.
    add_line(admin_conn, seller, d, "D", order_no="CN2", package=922, line_id=42, order_status="Cancelled")
    add_line(admin_conn, seller, d, "D", order_no="CN2", package=923, line_id=42, line_status="UnSupplied")
    assert by_barcode(await load(sessions, seller)) == {"C": (1, 1, 0, 0)}
