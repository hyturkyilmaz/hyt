"""Demo veri tohumunun SAF veri tanımları (veritabanı yok; docs/ux/kullanici_testi_plani_S4.md §7.1).

Bu modül yalnız "ne eklenecek"i söyler: ürünler, siparişler, ekstre ve kargo faturası kayıtları, ürün
maliyetleri ve kâr ayarları. Rakamların doğru cevabı burada YAZILMAZ; cevap kartı (`demo_card`) gerçek kâr
motorunu ve rapor servislerini çalıştırarak üretir. Burada yalnız senaryo rolleri (hangi sipariş "çok
ürünlü", hangisi "ekstresi gelmeyen" vb.) etiketlenir.

KVKK: Son müşteriye ait hiçbir alan YOKTUR (ad, adres, telefon, e-posta, TCKN, il bile yok); yalnız uydurma
ürün adları, sipariş numaraları ve tutarlar vardır. Satıcı, ürün ve marka adları açıkça sahte ("Demo ...").

Tüm tarihler `as_of` (İstanbul günü) ile göreli verilir: betik yeniden çalıştırılınca aynı kayıtlar yeni
tarihlere kayar (doğal anahtarlar sabit olduğu için çoğalma olmaz).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

# Tohum şeması sürümü: doğal anahtarlar ya da senaryo rolleri değişirse artırılır. Aynı veritabanında farklı
# sürümle tohumlama reddedilir (betik yalnız ekler/günceller, silmez; yeni sürüm için temiz veritabanı gerekir).
SEED_VERSION = "1"

D = Decimal
ISTANBUL = timezone(timedelta(hours=3))

# Sabit başlangıç tarihi: ayar sürümleri ve ürün maliyetleri her `as_of` için dönemin öncesinden geçerlidir.
EPOCH_DAY = date(2026, 1, 1)
MIN_AS_OF = date(2026, 3, 1)

# Veri `as_of`'tan en çok bu kadar gün öncesine uzanır: panelde "30 gün" üç gün boyunca aynı kümeyi görür.
MAX_DAYS_AGO = 27
# Ekstresi (hakediş) gelmiş sayılan en yeni sipariş yaşı; daha yeniler doğal olarak "ekstresi gelmedi" olur.
SETTLED_FROM_DAYS_AGO = 6

SELLER_PAYS_CARGO = 1  # whoPays=1: satıcının kendi kargo anlaşması (motorun `SELLER_PAYS_CARGO` sabiti)
CARRIER = "Trendyol Express"
SELLER_CARRIER = "Aras Kargo Marketplace"

DatasetKey = Literal["x", "y"]


@dataclass(frozen=True, slots=True)
class DemoProduct:
    barcode: str
    title: str
    stock_code: str
    vat: int
    commission: Decimal  # yüzde
    unit_desi: Decimal
    cost: Decimal | None  # birim maliyet, KDV hariç; None = maliyet girilmemiş
    category: str = "Demo Kategori"


@dataclass(frozen=True, slots=True)
class DemoLine:
    line_id: int
    barcode: str
    quantity: int
    unit_gross: Decimal  # KDV dahil birim fiyat
    vat: Decimal
    commission: Decimal


@dataclass(frozen=True, slots=True)
class DemoOrder:
    number: str
    package_id: int
    days_ago: int
    hour: int
    lines: tuple[DemoLine, ...]
    status: str = "Delivered"
    carrier: str = CARRIER
    cargo_deci: Decimal | None = Decimal(2)
    who_pays: int | None = None
    # Ekstre (hakediş) satırı üretilsin mi (Sale). Yanlışsa sipariş "ekstresi gelmedi" kalır.
    settled: bool = False
    # Ekstredeki komisyon oranı; satır oranından farklıysa "beklenmeyen kesinti" üretir (docs/12 K23, G27).
    statement_rate: Decimal | None = None
    # Satır kimliği -> iade adedi. Ekstrede Return satırı yazılır, iade kaydı (claim) YAZILMAZ: motor
    # "İade kaydı bekleniyor" der (K10, G47).
    returned_units: tuple[tuple[int, int], ...] = ()
    # Kargo faturası kalemi: (gönderi tutarı KDV dahil, desi); iade kargosu ayrıca verilebilir.
    invoice_outbound: tuple[Decimal, int] | None = None
    invoice_return: tuple[Decimal, int] | None = None
    payment_order_id: int | None = None
    role: str | None = None


@dataclass(frozen=True, slots=True)
class DemoSettings:
    """Kâr ayarları (hepsi KDV dahil girilmiş gibi saklanır, paneldeki varsayılan giriş biçimi)."""

    tariff: tuple[tuple[Decimal, Decimal], ...] = ()  # (en çok desi, fiyat KDV dahil)
    service_fee: Decimal | None = None  # sipariş başına, KDV dahil
    default_desi: Decimal | None = None
    expense_name: str | None = None
    expense_amount: Decimal | None = None  # sipariş başına, KDV hariç


@dataclass(frozen=True, slots=True)
class DemoAccountData:
    key: str  # "a", "bx", "by"
    title: str
    products: tuple[DemoProduct, ...]
    orders: tuple[DemoOrder, ...]
    settings: DemoSettings
    # Rol adı -> barkod ya da sipariş numarası (liste için virgülle ayrılmış değil, ayrı alanlar)
    roles: dict[str, str] = field(default_factory=dict)


def _q(value: str) -> Decimal:
    return Decimal(value)


def order_moment(as_of: date, days_ago: int, hour: int) -> datetime:
    """Sipariş anı: `as_of - days_ago` İstanbul gününün `hour:15` saati (UTC'ye çevrilmiş, saat dilimli)."""
    day = as_of - timedelta(days=days_ago)
    return datetime.combine(day, time(hour, 15), tzinfo=ISTANBUL).astimezone(timezone.utc)  # noqa: UP017


def _line(n: int, product: DemoProduct, qty: int, price: Decimal) -> DemoLine:
    return DemoLine(n, product.barcode, qty, price, Decimal(product.vat), product.commission)


# --------------------------------------------------------------------------------------------- Hesap A

# (başlık, fiyat KDV dahil, KDV, komisyon, desi, maliyet oranı pozitif varyant, negatif varyant)
_A_SPECS: tuple[tuple[str, str, int, str, str, str, str], ...] = (
    ("Demo Ürün: Bambu Kesme Tahtası", "249.90", 20, "15", "2", "0.42", "0.97"),
    ("Demo Ürün: Seramik Kupa Seti", "329.90", 20, "16", "3", "0.40", "0.95"),
    ("Demo Ürün: Pamuklu Mutfak Önlüğü", "189.90", 10, "14", "1", "0.45", "0.98"),
    ("Demo Ürün: Cam Baharatlık Takımı", "189.90", 20, "17", "2", "0.44", "0.96"),
    ("Demo Ürün: Katlanır Çamaşır Sepeti", "279.90", 20, "15", "4", "0.41", "0.97"),
    ("Demo Ürün: Metal Telefon Standı", "229.90", 20, "18", "1", "0.43", "0.99"),
    ("Demo Ürün: Dikişsiz Spor Çorap (12'li)", "229.90", 10, "13", "1", "0.46", "0.98"),
    ("Demo Ürün: Ahşap Fincan Altlığı (6'lı)", "209.90", 20, "16", "2", "0.42", "0.96"),
)


def a_costs(variant: Literal["positive", "negative"]) -> dict[str, Decimal]:
    """Hesap A ürün maliyetleri (KDV hariç). `negative`: bilinen giderlerle bile zarar varyantı."""
    costs: dict[str, Decimal] = {}
    for i, spec in enumerate(_A_SPECS, start=1):
        price, vat, ratio = (
            Decimal(spec[1]),
            Decimal(spec[2]),
            Decimal(spec[5] if variant == "positive" else spec[6]),
        )
        net = price / (1 + vat / 100)
        costs[_a_barcode(i)] = (net * ratio).quantize(Decimal("0.01"))
    return costs


def _a_barcode(i: int) -> str:
    return f"9900000000{i:03d}"


def build_account_a(instance: int) -> DemoAccountData:
    """Hesap A: ayarsız, yeni bağlanmış. Maliyetler dolu; kargo tarifesi, hizmet bedeli, varsayılan desi YOK."""
    base = 7_100_000 + instance * 1000
    products = tuple(
        DemoProduct(
            barcode=_a_barcode(i),
            title=spec[0],
            stock_code=f"DEMO-A-{i:03d}",
            vat=spec[2],
            commission=_q(spec[3]),
            unit_desi=_q(spec[4]),
            cost=a_costs("positive")[_a_barcode(i)],
        )
        for i, spec in enumerate(_A_SPECS, start=1)
    )
    orders: list[DemoOrder] = []
    for n in range(40):
        product = products[(n * 3) % len(products)]
        qty = 1 + (n % 4 == 3)
        days_ago = 1 + (n * 7) % MAX_DAYS_AGO
        price = Decimal(_A_SPECS[(n * 3) % len(products)][1])
        settled = days_ago >= SETTLED_FROM_DAYS_AGO and n % 5 != 4
        status = "Cancelled" if n % 17 == 16 else "Delivered"
        orders.append(
            DemoOrder(
                number=str(base + n + 1),
                package_id=8_000_000 + instance * 1000 + n + 1,
                days_ago=days_ago,
                hour=9 + n % 11,
                lines=(_line(base + n + 1, product, qty, price),),
                status=status,
                cargo_deci=product.unit_desi * qty,
                settled=settled and status == "Delivered",
                payment_order_id=9_100_000 + instance * 100 + days_ago // 7 if settled else None,
            )
        )
    return DemoAccountData(
        key="a",
        title="Hesap A (ayarsız)",
        products=products,
        orders=tuple(orders),
        settings=DemoSettings(),
        roles={},
    )


# --------------------------------------------------------------------------------------------- Hesap B


@dataclass(frozen=True, slots=True)
class _Hero:
    """Bir senaryo ürünü: ad, fiyat (KDV dahil), komisyon, desi, maliyet (None = girilmemiş) ve satış adedi."""

    title: str
    price: str
    commission: str
    desi: str
    cost: str | None
    orders: int
    qty: int = 1


@dataclass(frozen=True, slots=True)
class _Set:
    """Veri seti (X ya da Y): farklı ürün, sipariş ve en çok zarar eden."""

    key: DatasetKey
    code: int  # sipariş/paket numarası ve barkod öneki
    # Üç zarar ürünü: kesin zarar, bilinen giderlerle bile zarar, maliyet girilmese de zarar.
    loss_net: _Hero
    loss_known: _Hero  # satıcının kendi kargo anlaşmasıyla gider: kargo eksik kalır
    loss_nocost: _Hero
    nocost_other: _Hero  # maliyeti girilmemiş, kârlı ürün
    # Çok ürünlü sipariş: (ürün adı, adet, iade adedi); iki satır
    multi: tuple[tuple[str, int, int], tuple[str, int, int]]
    unexpected_orders: int  # beklenmeyen kesinti siparişi sayısı (1 ya da 2)
    old_awaiting: int  # uzun süredir ekstresi gelmeyen sipariş sayısı


_FILLERS: tuple[tuple[str, str, int, str, str, str], ...] = (
    ("Bambu Kesme Tahtası", "249.90", 20, "15", "2", "0.42"),
    ("Seramik Kupa Seti", "329.90", 20, "16", "3", "0.40"),
    ("Pamuklu Mutfak Önlüğü", "189.90", 10, "14", "1", "0.45"),
    ("Cam Baharatlık Takımı", "189.90", 20, "17", "2", "0.44"),
    ("Katlanır Çamaşır Sepeti", "279.90", 20, "15", "4", "0.41"),
    ("Metal Telefon Standı", "229.90", 20, "18", "1", "0.43"),
    ("Dikişsiz Spor Çorap (12'li)", "229.90", 10, "13", "1", "0.46"),
    ("Ahşap Fincan Altlığı (6'lı)", "209.90", 20, "16", "2", "0.42"),
    ("Silikon Mutfak Spatula Seti", "199.90", 20, "15", "1", "0.40"),
    ("Paslanmaz Çelik Termos", "399.90", 20, "14", "3", "0.43"),
    ("Pamuklu Banyo Havlusu", "259.90", 10, "13", "3", "0.44"),
    ("Dekoratif Yastık Kılıfı (2'li)", "199.90", 10, "15", "1", "0.41"),
    ("Mıknatıslı Baharat Rafı", "209.90", 20, "16", "2", "0.40"),
    ("Cam Saklama Kabı (5'li)", "299.90", 20, "15", "4", "0.42"),
    ("Masa Üstü Organizer", "219.90", 20, "17", "2", "0.43"),
    ("Antibakteriyel Süngerlik (10'lu)", "199.90", 20, "18", "1", "0.38"),
    ("Kampanya Piknik Örtüsü", "179.90", 20, "14", "2", "0.40"),
)

_SETS: dict[DatasetKey, _Set] = {
    "x": _Set(
        key="x",
        code=2,
        loss_net=_Hero("Büyük Boy Saklama Sandığı", "139.90", "15", "8", "78.00", orders=20),
        loss_known=_Hero("Kendi Kargomla Giden Poşet Seti", "89.90", "18", "1", "60.00", orders=10),
        loss_nocost=_Hero("Ucuz Mutfak Askısı", "59.90", "20", "1", None, orders=9),
        nocost_other=_Hero("Premium Seyahat Çantası", "399.90", "14", "3", None, orders=5),
        multi=(("Seramik Kupa Seti", 2, 1), ("Bambu Kesme Tahtası", 1, 0)),
        unexpected_orders=2,
        old_awaiting=2,
    ),
    "y": _Set(
        key="y",
        code=3,
        loss_net=_Hero("Dolgulu Yatak Minderi", "219.90", "18", "10", "140.00", orders=14),
        loss_known=_Hero("Kendi Kargomla Giden Baskılı Kutu", "109.90", "17", "1", "72.00", orders=9),
        loss_nocost=_Hero("Mini Plastik Tarak Seti", "49.90", "19", "1", None, orders=8),
        nocost_other=_Hero("Deri Cüzdan Kutusu", "349.90", "15", "2", None, orders=4),
        multi=(("Cam Baharatlık Takımı", 3, 1), ("Metal Telefon Standı", 1, 0)),
        unexpected_orders=1,
        old_awaiting=3,
    ),
}


def _hero_product(prefix: int, slot: int, hero: _Hero, vat: int = 20) -> DemoProduct:
    return DemoProduct(
        barcode=f"99{prefix:02d}0000{slot:04d}",
        title=f"Demo Ürün: {hero.title}",
        stock_code=f"DEMO-B{prefix}-{slot:03d}",
        vat=vat,
        commission=_q(hero.commission),
        unit_desi=_q(hero.desi),
        cost=None if hero.cost is None else _q(hero.cost),
    )


def b_tariff() -> tuple[tuple[Decimal, Decimal], ...]:
    """Bilgi kartındaki tarife (KDV dahil): 0-2 desi 50, 3-5 desi 60, 6-10 desi 80 TL."""
    return ((D(2), D("50.00")), (D(5), D("60.00")), (D(10), D("80.00")))


def build_account_b(dataset: DatasetKey, instance: int) -> DemoAccountData:
    """Hesap B: ayarlı. Üç zarar ürünü, maliyeti eksik ürün, çok ürünlü + iadeli sipariş, ekstresi gelmeyen
    ve beklenmeyen kesintili siparişler. `dataset` X ya da Y: ürün, sipariş ve en çok zarar eden farklıdır."""
    spec = _SETS[dataset]
    code = spec.code
    base = 7_000_000 + code * 100_000 + instance * 1000
    pkg_base = 8_000_000 + code * 100_000 + instance * 1000

    fillers = [
        DemoProduct(
            barcode=f"99{code:02d}0000{i:04d}",
            title=f"Demo Ürün: {name}",
            stock_code=f"DEMO-B{code}-{i:03d}",
            vat=vat,
            commission=_q(comm),
            unit_desi=_q(desi),
            cost=((Decimal(price) / (1 + Decimal(vat) / 100)) * Decimal(ratio)).quantize(Decimal("0.01")),
        )
        for i, (name, price, vat, comm, desi, ratio) in enumerate(_FILLERS, start=1)
    ]
    prices = {f.barcode: Decimal(p[1]) for f, p in zip(fillers, _FILLERS, strict=True)}
    loss_net = _hero_product(code, 101, spec.loss_net)
    loss_known = _hero_product(code, 102, spec.loss_known)
    loss_nocost = _hero_product(code, 103, spec.loss_nocost)
    nocost_other = _hero_product(code, 104, spec.nocost_other)
    # Fillers listesinde ürün adıyla çok ürünlü sipariş ürünleri bulunur.
    by_title = {f.title.removeprefix("Demo Ürün: "): f for f in fillers}
    products = (*fillers, loss_net, loss_known, loss_nocost, nocost_other)
    hero_prices = {
        loss_net.barcode: Decimal(spec.loss_net.price),
        loss_known.barcode: Decimal(spec.loss_known.price),
        loss_nocost.barcode: Decimal(spec.loss_nocost.price),
        nocost_other.barcode: Decimal(spec.nocost_other.price),
    }
    prices.update(hero_prices)

    orders: list[DemoOrder] = []
    counter = 0

    def next_ids() -> tuple[str, int, int]:
        nonlocal counter
        counter += 1
        return str(base + counter), pkg_base + counter, base + counter * 10

    def payment(days_ago: int) -> int:
        return 9_200_000 + code * 1000 + instance * 10 + days_ago // 7

    def add(
        product: DemoProduct,
        qty: int,
        days_ago: int,
        *,
        settled: bool | None = None,
        **extra: object,
    ) -> None:
        number, package, line_id = next_ids()
        is_settled = days_ago >= SETTLED_FROM_DAYS_AGO if settled is None else settled
        orders.append(
            DemoOrder(
                number=number,
                package_id=package,
                days_ago=days_ago,
                hour=9 + counter % 11,
                lines=(_line(line_id, product, qty, prices[product.barcode]),),
                cargo_deci=product.unit_desi * qty,
                settled=is_settled,
                payment_order_id=payment(days_ago) if is_settled else None,
                **extra,  # type: ignore[arg-type]
            )
        )

    # Dolgu ürünleri: kârlı, çeşitli hacim ve gün.
    for i in range(46):
        product = fillers[(i * 5) % len(fillers)]
        add(product, 1 + (i % 5 == 4), 1 + (i * 11) % MAX_DAYS_AGO)
    # İptal edilen birkaç sipariş.
    for i in range(3):
        add(fillers[i], 1, 8 + i * 4, settled=False, status="Cancelled")

    # Senaryo ürünleri.
    for i in range(spec.loss_net.orders):
        add(loss_net, spec.loss_net.qty, 2 + (i * 5) % 25)
    for i in range(spec.loss_known.orders):
        add(
            loss_known,
            spec.loss_known.qty,
            3 + (i * 7) % 24,
            who_pays=SELLER_PAYS_CARGO,
            carrier=SELLER_CARRIER,
        )
    for i in range(spec.loss_nocost.orders):
        add(loss_nocost, spec.loss_nocost.qty, 2 + (i * 3) % 25)
    for i in range(spec.nocost_other.orders):
        add(nocost_other, spec.nocost_other.qty, 4 + (i * 6) % 22)

    roles: dict[str, str] = {
        "loss_net": loss_net.barcode,
        "loss_known": loss_known.barcode,
        "loss_nocost": loss_nocost.barcode,
        "nocost_other": nocost_other.barcode,
    }

    # Çok ürünlü + iadeli sipariş (G5): iki satır, kargo faturası (gönderi + iade), 1 adet iade, iade kaydı yok.
    (title1, qty1, ret1), (title2, qty2, _ret2) = spec.multi
    p1, p2 = by_title[title1], by_title[title2]
    number, package, line_id = next_ids()
    orders.append(
        DemoOrder(
            number=number,
            package_id=package,
            days_ago=12,
            hour=14,
            lines=(
                _line(line_id, p1, qty1, prices[p1.barcode]),
                _line(line_id + 1, p2, qty2, prices[p2.barcode]),
            ),
            cargo_deci=D(4),
            settled=True,
            returned_units=((line_id, ret1),),
            invoice_outbound=(D("60.00"), 4),
            invoice_return=(D("60.00"), 4),
            payment_order_id=payment(12),
            role="multi_order",
        )
    )
    roles["multi_order"] = number

    # Beklenmeyen kesinti 1: ekstredeki komisyon oranı sipariş satırından yüksek (G27).
    up = by_title["Paslanmaz Çelik Termos"]
    number, package, line_id = next_ids()
    orders.append(
        DemoOrder(
            number=number,
            package_id=package,
            days_ago=15,
            hour=11,
            lines=(_line(line_id, up, 1, prices[up.barcode]),),
            cargo_deci=up.unit_desi,
            settled=True,
            statement_rate=up.commission + D(4),
            payment_order_id=payment(15),
            role="unexpected_commission",
        )
    )
    roles["unexpected_commission"] = number
    # Beklenmeyen kesinti 2 (yalnız X): siparişte desi yok (varsayılan desi 2 kullanılır), kargo faturasında 5 desi.
    if spec.unexpected_orders >= 2:
        ud = by_title["Cam Saklama Kabı (5'li)"]
        number, package, line_id = next_ids()
        orders.append(
            DemoOrder(
                number=number,
                package_id=package,
                days_ago=18,
                hour=16,
                lines=(_line(line_id, ud, 1, prices[ud.barcode]),),
                cargo_deci=None,
                settled=True,
                invoice_outbound=(D("95.00"), 5),
                payment_order_id=payment(18),
                role="unexpected_cargo",
            )
        )
        roles["unexpected_cargo"] = number

    # Uzun süredir ekstresi gelmeyen siparişler (ekstresiz kalan eski siparişler, "hakediş bekleyen").
    for i in range(spec.old_awaiting):
        product = fillers[(i * 7 + 2) % len(fillers)]
        add(product, 1, 19 + i * 3, settled=False, role=f"old_awaiting_{i + 1}")
        roles[f"old_awaiting_{i + 1}"] = orders[-1].number

    return DemoAccountData(
        key=f"b{dataset}",
        title=f"Hesap B (ayarlı, veri seti {dataset.upper()})",
        products=products,
        orders=tuple(orders),
        settings=DemoSettings(
            tariff=b_tariff(),
            service_fee=D("10.00"),
            default_desi=D(2),
            expense_name="Koli ve bant",
            expense_amount=D("2.50"),
        ),
        roles=roles,
    )


# Bilgi kartı (plan §4, G2): Hesap A katılımcısının girdiği değerler. Cevap kartı bu değerlerle "girildikten
# sonra" rakamını motordan hesaplar; G3'te 3-5 desi fiyatı 65 TL olur.
INFO_CARD_TARIFF: tuple[tuple[Decimal, Decimal], ...] = b_tariff()
INFO_CARD_SERVICE_FEE = D("10.00")
INFO_CARD_TARIFF_AFTER_G3: tuple[tuple[Decimal, Decimal], ...] = (
    (D(2), D("50.00")),
    (D(5), D("65.00")),
    (D(10), D("80.00")),
)
