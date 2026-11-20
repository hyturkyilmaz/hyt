"""İade kohort sorgusu (ADR-0009 D3, §3.4): veritabanından `ReturnCohort` sayımlarını üretir.

Bu modül veritabanına dokunan besleyicidir; `app/alerts` kuralları (`rules.py`, `stats.py`) saf kalır, yalnız
buradan dönen sayıları okur.

Sayım birimi MANTIKSAL sipariş satırıdır: (`order_number`, `line_id`). Paket bölünürse (splitShipmentPackage)
eski paket `UnPacked` olur ve aynı `lineId` yeni pakette sürer; iki paket satırı da `order_lines` içinde
durur.
Bu yüzden satır başına tek kayıt seçilir (`DISTINCT ON`): `UnPacked` paket her zaman yenisine yenilir,
kalanlar
arasında en son değişen paket (`last_modified_at`, yoksa `ordered_at`, sonra `shipment_package_id`) kazanır.
Seçilen kayıt hâlâ `UnPacked` ise (yeni paket henüz senkronlanmadı) satır sayılmaz. `n` = kohorttaki mantıksal
satır sayısı, `x` = en az bir sayılan iade kalemi olan mantıksal satır sayısı; neden kodları da satır başına
bir kez sayılır. Kohortlar `stats.cohort_windows` ile gelir (sipariş günü, İstanbul, yarı açık).

Dışlananlar (hepsi `EXCLUDED_ORDER_STATUSES`): iptal (`Cancelled`, `UnSupplied`, K26) ve `UnPacked`. Fark
(D3):
motor yalnız SİPARİŞ durumuna bakar; burada satır durumu (`orderLineItemStatusName`) de aynı kümeyle dışlanır,
çünkü kısmi iptalde satır, paket durumundan önce iptal görünebilir. `UnDelivered` (müşteriye
ulaştırılamadı) ve
`Returned` DIŞLANMAZ: motor da bunları iptal saymaz (K26); satış yapılmamış gibi dışlamak paydayı küçültüp
oranı şişirirdi, dahil etmek ihtiyatlıdır (oranı düşük tutar, yanlış pozitifi azaltır).

İade eşlemesi: motorun anahtarı (`costs.apply_refund_items`, K10) `order_number` ile iade kaleminin
`order_line_item_id` değerinin satırın `discountDetails.lineItemId` kümesinde (`order_lines.items[].id`)
bulunmasıdır. Öncelik: `order_line_item_id` DOLUYSA yalnız bu yol (a) kullanılır ve mantıksal satırın TÜM
paket
kayıtlarına karşı aranır (bölünmede kalem kimlikleri eski pakette kalmış olabilir); (b)
`returns.order_line_id =
order_lines.line_id` (claim `orderLine.id` ile sipariş `lineId` aynı varlık kabulü) yalnız kalem kimliği
BOŞKEN
kullanılır. (b) belgelerle ya da fixture'larla doğrulanmadı (claims ve shipment fixture'ları aynı siparişte
buluşmaz; bkz. test); uydurma eşleme yoktur. Eşleşemeyen kayıtlar sayılır ve çağırana döner
(`unmatched_returns`:
anahtar eksik, `orphan_returns`: anahtar dolu ama satır yok, `ambiguous_returns`: kalem birden çok mantıksal
satıra bağlanıyor), sessiz kaybolmaz.

Bölünmede ayrıca: satırın kayıtlarından biri iptal ya da `UnPacked` iken diğeri değilse iptal olmayan kayıt
seçilir; mantıksal satır yalnız TÜM kayıtları dışlanan durumdaysa düşer.

Performans (ölçülmedi): iade bağlama sayımı (`return_links`) hesabın tüm sayılan iadelerini tarar ve her biri
için `order_lines.items` üzerinde JSONB kapsama (`@>`) arar; kalem anahtarı için `returns` üzerinde indeks ve
`items` üzerinde GIN indeksi yoktur. Günlük değerlendirmede hesap başına bir kez çalışır; yavaşlarsa
`returns (marketplace_account_id, order_line_item_id)` ve `order_lines USING gin (items)` indeksleri ya da
sayımın pencereyle sınırlanması düşünülmeli.

Ufuk filtresi İKİ kohorta aynı SQL ifadesiyle uygulanır: sayılan iade, `claim_date <= ordered_at + H`
koşulunu sağlar. Pencere ucu (`T-H`) her satırın en az `H` gün yaşlı olmasını sağlar; `n` ufuktan etkilenmez.
UYARI (gözlem süresi eşit DEĞİLDİR): ufuk yalnız iadenin AÇILIŞ tarihini sınırlar, iade durumunun
olgunlaşmasını
değil. Güncel kohortun iadeleri `Accepted` durumuna henüz geçmemiş olabilir (`Created` vb.), taban kohortunki
çoktan geçmiştir. Etki yönü: güncel kohort göreli EKSİK sayılır, yani yanlış NEGATİF (geç ya da hiç alarm
yok);
alarm üretme yönünde sapma yoktur (ihtiyatlı).

Müşteri kişisel verisi okunmaz: yalnız sipariş/satır/iade anahtarları, barkod, statü, tarih ve neden kodu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.rules import ReturnCohort
from app.alerts.stats import HORIZON_DAYS, cohort_windows
from app.db.rls import set_rls_context
from app.profit.constants import CANCELLED_STATUSES
from app.profit.costs import ACCEPTED_CLAIM_STATUS
from app.profit.schema_v1 import ISTANBUL

# Sayılan iade statüsü: tek sabit. Doğrulanmadı (ADR-0009 §3.4): kodda yalnız "Accepted" adı bilinir;
# "reddedilen hariç tüm talepler" kümesi pilot veriyle belirlenecek. Bu seçim iade sayısını eksik sayar
# (yanlış pozitifi azaltır, gecikmeyi artırır). Küme genişletilirse yalnız bu sabit değişir (SQL bağlı
# parametre kullanır).
COUNTED_RETURN_STATUSES: tuple[str, ...] = (ACCEPTED_CLAIM_STATUS,)

# Dışlanan sipariş/satır durumları: iptal (K26) ve bölünmüş eski paket. `UnDelivered` kasıtlı olarak dışarıda
# bırakılmaz (modül docstring'i).
UNPACKED_STATUS = "UnPacked"
EXCLUDED_ORDER_STATUSES: tuple[str, ...] = (*sorted(CANCELLED_STATUSES), UNPACKED_STATUS)

# Neden kodu sayısı (yüke en çok ilk 3 girer, ADR-0009 §3.4 "Yük").
MAX_REASON_CODES = 3

# Tek SQL, düz sabit dizge: değerlerin hepsi bağlı parametredir (f-string ve birleştirme yok).
# - `packaged`: pencere süzgeciyle mantıksal satır başına tek paket kaydı (UnPacked yenilir, sonra en son
#   değişen).
# - `windowed`/`cohort_lines`: seçilen kaydın durumu iptal ya da UnPacked ise dışarıda; `is_current`
#   güncel/taban ayrımıdır. Pencereler ayrık olduğundan satır tek kohorta düşer.
# - `matched`: satırla (sipariş no + satır kimliği) eşleşen, sayılan statüde ve ufuk içinde açılmış iadeler.
# - `flagged`: satır başına "iade edilmiş mi" (EXISTS; aynı satırın birden çok iade kalemi tek sayılır).
# - `counts`: ROLLUP ile barkod başına ve hesap toplamı (GROUPING) tek geçişte.
# - `return_links`/`link_counts`: sayılan statüdeki iadelerden anahtarı eksik olanlar (`unmatched_returns`)
#   ve anahtarı
#   dolu olup hesapta karşılığı bir `order_lines` satırı bulunmayanlar (`orphan_returns`); hesap geneli,
#   pencere
#   bağımsız (iptal ya da silinmiş satır karşılık sayılır).
# - `top_reasons`: yalnız güncel kohorttaki iadelerin en sık ilk 3 neden kodu (serbest metin yok).
_COHORT_SQL = text(
    """
    WITH packaged AS (
        SELECT DISTINCT ON (o.order_number, l.line_id)
               l.id AS line_pk, l.barcode, l.line_id, l.items, o.order_number, o.ordered_at,
               o.status AS order_status, l.status AS line_status
        FROM order_lines l
        JOIN orders o ON o.id = l.order_id AND o.tenant_id = l.tenant_id
        WHERE l.tenant_id = :tenant_id AND l.marketplace_account_id = :account_id
          AND o.tenant_id = :tenant_id AND o.marketplace_account_id = :account_id
          AND l.removed_at IS NULL
          AND o.ordered_at >= :base_lo AND o.ordered_at < :cur_hi
        ORDER BY o.order_number, l.line_id, (o.status = :unpacked_status),
                 (o.status IN :excluded OR COALESCE(l.status IN :excluded, FALSE)),
                 COALESCE(o.last_modified_at, o.ordered_at) DESC, o.shipment_package_id DESC
    ),
    windowed AS (
        SELECT line_pk, barcode, line_id, items, order_number, ordered_at,
               CASE
                   WHEN ordered_at >= :cur_lo AND ordered_at < :cur_hi THEN TRUE
                   WHEN ordered_at >= :base_lo AND ordered_at < :base_hi THEN FALSE
               END AS is_current
        FROM packaged
        WHERE order_status NOT IN :excluded
          AND (line_status IS NULL OR line_status NOT IN :excluded)
    ),
    cohort_lines AS (
        SELECT line_pk, barcode, line_id, items, order_number, ordered_at, is_current
        FROM windowed
        WHERE is_current IS NOT NULL
    ),
    matched AS (
        SELECT cl.line_pk, cl.barcode, cl.is_current, r.reason_code
        FROM cohort_lines cl
        JOIN returns r
          ON r.order_number = cl.order_number
         AND (
              (r.order_line_item_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                   FROM order_lines l2
                   JOIN orders o2 ON o2.id = l2.order_id AND o2.tenant_id = l2.tenant_id
                   WHERE l2.tenant_id = :tenant_id AND l2.marketplace_account_id = :account_id
                     AND o2.tenant_id = :tenant_id AND o2.marketplace_account_id = :account_id
                     AND o2.order_number = cl.order_number AND l2.line_id = cl.line_id
                     AND l2.items @> jsonb_build_array(jsonb_build_object('id', r.order_line_item_id))))
              OR (r.order_line_item_id IS NULL AND r.order_line_id IS NOT NULL
                  AND r.order_line_id = cl.line_id)
         )
        WHERE r.tenant_id = :tenant_id AND r.marketplace_account_id = :account_id
          AND r.status IN :counted_statuses
          AND r.claim_date IS NOT NULL
          AND r.claim_date <= cl.ordered_at + (CAST(:horizon_hours AS integer) * INTERVAL '1 hour')
    ),
    flagged AS (
        SELECT cl.barcode, cl.is_current,
               EXISTS (SELECT 1 FROM matched m WHERE m.line_pk = cl.line_pk) AS returned
        FROM cohort_lines cl
    ),
    counts AS (
        SELECT barcode, GROUPING(barcode) = 1 AS is_total,
               COUNT(*) FILTER (WHERE is_current) AS current_lines,
               COUNT(*) FILTER (WHERE is_current AND returned) AS current_returned,
               COUNT(*) FILTER (WHERE NOT is_current) AS base_lines,
               COUNT(*) FILTER (WHERE NOT is_current AND returned) AS base_returned
        FROM flagged
        GROUP BY ROLLUP (barcode)
    ),
    ranked_reasons AS (
        SELECT barcode, reason_code,
               ROW_NUMBER() OVER (
                   PARTITION BY barcode ORDER BY COUNT(DISTINCT line_pk) DESC, reason_code
               ) AS rn
        FROM matched
        WHERE is_current AND reason_code IS NOT NULL
        GROUP BY barcode, reason_code
    ),
    top_reasons AS (
        SELECT barcode, ARRAY_AGG(reason_code ORDER BY rn) AS reason_codes
        FROM ranked_reasons
        WHERE rn <= :max_reason_codes
        GROUP BY barcode
    ),
    return_links AS (
        SELECT (r.claim_date IS NULL OR r.order_number IS NULL
                OR (r.order_line_id IS NULL AND r.order_line_item_id IS NULL)) AS unlinkable,
               (
                   SELECT COUNT(DISTINCT l.line_id)
                   FROM order_lines l
                   JOIN orders o ON o.id = l.order_id AND o.tenant_id = l.tenant_id
                   WHERE l.tenant_id = :tenant_id AND l.marketplace_account_id = :account_id
                     AND o.tenant_id = :tenant_id AND o.marketplace_account_id = :account_id
                     AND o.order_number = r.order_number
                     AND (
                          (r.order_line_item_id IS NOT NULL
                           AND l.items @> jsonb_build_array(jsonb_build_object('id', r.order_line_item_id)))
                          OR (r.order_line_item_id IS NULL AND r.order_line_id IS NOT NULL
                              AND r.order_line_id = l.line_id)
                     )
               ) AS line_matches
        FROM returns r
        WHERE r.tenant_id = :tenant_id AND r.marketplace_account_id = :account_id
          AND r.status IN :counted_statuses
    ),
    link_counts AS (
        SELECT COUNT(*) FILTER (WHERE unlinkable) AS unmatched_returns,
               COUNT(*) FILTER (WHERE NOT unlinkable AND line_matches = 0) AS orphan_returns,
               COUNT(*) FILTER (WHERE NOT unlinkable AND line_matches > 1) AS ambiguous_returns
        FROM return_links
    )
    SELECT c.barcode, c.is_total, c.current_lines, c.current_returned, c.base_lines, c.base_returned,
           t.reason_codes, u.unmatched_returns, u.orphan_returns, u.ambiguous_returns
    FROM counts c
    LEFT JOIN top_reasons t ON t.barcode = c.barcode
    CROSS JOIN link_counts u
    ORDER BY c.is_total, c.barcode
    """
).bindparams(
    bindparam("excluded", expanding=True),
    bindparam("counted_statuses", expanding=True),
)


class TenantContextMismatch(RuntimeError):
    """Oturumda başka bir kiracının RLS bağlamı kurulu (çağıran hatası; sessizce ezilmez)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountReturnCounts:
    """Hesap düzeyi toplam (SQL'de ROLLUP ile ayrıca hesaplanır; ürün toplamlarıyla eşit olmalıdır)."""

    current_lines: int
    current_returned: int
    base_lines: int
    base_returned: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ReturnCohortSet:
    """Sorgu çıktısı: ürün kohortları (barkoda göre sıralı) ve hesap toplamı."""

    products: tuple[ReturnCohort, ...]
    account: AccountReturnCounts
    # Sayılan statüde olup bağlanamayan iade kalemi: claim_date, order_number ya da her iki satır anahtarı
    # boş.
    unmatched_returns: int = 0
    # Anahtarları dolu ama hesapta karşılığı olan sipariş satırı bulunmayan (yetim) sayılan iade kalemi.
    orphan_returns: int = 0
    # Kalem anahtarı birden çok mantıksal satıra bağlanan sayılan iade kalemi (belirsiz; kohortta
    # bağlandığı her
    # satırı iade sayar).
    ambiguous_returns: int = 0


def istanbul_day_start(day: date) -> datetime:
    """İstanbul gününün başlangıcı (00:00, UTC+3 sabit; motorun sipariş günü tanımıyla aynı, K16)."""
    return datetime.combine(day, time.min, tzinfo=ISTANBUL)


async def load_return_cohorts(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, as_of: date
) -> ReturnCohortSet:
    """`as_of` (değerlendirme günü, İstanbul) için ürün ve hesap kohort sayımlarını tek sorguyla okur.

    Kiracı RLS bağlamı burada işlem yerel olarak kurulur (`set_rls_context`); sorgu ayrıca açık `tenant_id` ve
    hesap süzgeci taşır (çift kilit). Oturumda başka kiracının bağlamı varsa `TenantContextMismatch` verir.
    Boş pencerede `products` boş, hesap toplamı sıfırdır.
    """
    cur_start, cur_end, base_start, base_end = cohort_windows(as_of)
    current = (await db.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
    if current and current != str(tenant_id):
        raise TenantContextMismatch("oturumda başka bir kiracının RLS bağlamı kurulu")
    await set_rls_context(db, tenant_id)
    rows = (
        await db.execute(
            _COHORT_SQL,
            {
                "tenant_id": tenant_id,
                "account_id": account_id,
                "cur_lo": istanbul_day_start(cur_start),
                "cur_hi": istanbul_day_start(cur_end),
                "base_lo": istanbul_day_start(base_start),
                "base_hi": istanbul_day_start(base_end),
                "excluded": list(EXCLUDED_ORDER_STATUSES),
                "unpacked_status": UNPACKED_STATUS,
                "counted_statuses": list(COUNTED_RETURN_STATUSES),
                "horizon_hours": int(timedelta(days=HORIZON_DAYS).total_seconds() // 3600),
                "max_reason_codes": MAX_REASON_CODES,
            },
        )
    ).all()

    products: list[ReturnCohort] = []
    account = AccountReturnCounts(current_lines=0, current_returned=0, base_lines=0, base_returned=0)
    unmatched = rows[0].unmatched_returns if rows else 0
    orphans = rows[0].orphan_returns if rows else 0
    ambiguous = rows[0].ambiguous_returns if rows else 0
    for row in rows:
        if row.is_total:
            account = AccountReturnCounts(
                current_lines=row.current_lines,
                current_returned=row.current_returned,
                base_lines=row.base_lines,
                base_returned=row.base_returned,
            )
            continue
        products.append(
            ReturnCohort(
                barcode=row.barcode,
                current_lines=row.current_lines,
                current_returned=row.current_returned,
                base_lines=row.base_lines,
                base_returned=row.base_returned,
                reason_codes=tuple(row.reason_codes or ()),
            )
        )
    return ReturnCohortSet(
        products=tuple(products),
        account=account,
        unmatched_returns=unmatched,
        orphan_returns=orphans,
        ambiguous_returns=ambiguous,
    )
