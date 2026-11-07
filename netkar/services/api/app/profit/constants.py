"""Ekstre işlem tipleri ve işaret kuralı (K05) ile kural sabitleri.

Sınıflandırma yanıttaki Türkçe `transactionType` metnine değil, motorun çektiği istek tipine göre yapılır.
"""

from __future__ import annotations

from types import MappingProxyType

# K04: gelir (credit - debt) tipleri. K29: DeliveryFee satış gibi işlenir (düşük güven, teyit bekliyor).
CORE_SALES_TYPES = frozenset(
    {
        "Sale",
        "PayByLink",
        "Discount",
        "DiscountCancel",
        "Coupon",
        "CouponCancel",
        "ProvisionPositive",
        "ProvisionNegative",
    }
)
REVENUE_TYPES = CORE_SALES_TYPES | {"DeliveryFee", "DeliveryFeeCancel"}
# K04: iade (debt - credit) tipleri.
REFUND_TYPES = frozenset({"Return", "ManualRefund", "ManualRefundCancel"})
# K05: hakediş ve komisyon düzeltmeleri.
ADJUSTMENT_TYPES = frozenset(
    {
        "SellerRevenuePositive",
        "SellerRevenueNegative",
        "SellerRevenuePositiveCancel",
        "SellerRevenueNegativeCancel",
        "CommissionPositive",
        "CommissionNegative",
        "CommissionPositiveCancel",
        "CommissionNegativeCancel",
    }
)
# Satırın "settled" sayılmasını sağlayan tipler (K22).
SALE_TRIGGER_TYPES = frozenset({"Sale", "PayByLink"})
# K28: iç tutarlılık kontrolü yalnız satış ve iade tiplerinde (K29 teslimat ücreti hariç).
CONSISTENCY_TYPES = CORE_SALES_TYPES | REFUND_TYPES

# K05: komisyon maliyet işareti (+1 komisyon yazıldı, -1 geri verildi, 0 etkisiz).
COMMISSION_SIGN = MappingProxyType(
    {
        "Sale": 1,
        "PayByLink": 1,
        "DiscountCancel": 1,
        "CouponCancel": 1,
        "ProvisionPositive": 1,
        "ManualRefundCancel": 1,
        "CommissionPositive": 1,
        "CommissionNegativeCancel": 1,
        "DeliveryFee": 1,
        "Return": -1,
        "Discount": -1,
        "Coupon": -1,
        "ProvisionNegative": -1,
        "ManualRefund": -1,
        "CommissionNegative": -1,
        "CommissionPositiveCancel": -1,
        "DeliveryFeeCancel": -1,
        "SellerRevenuePositive": 0,
        "SellerRevenueNegative": 0,
        "SellerRevenuePositiveCancel": 0,
        "SellerRevenueNegativeCancel": 0,
        # K30: kurumsal faturalı sipariş indirimleri gelir ve komisyon hesabına katılmaz.
        "TyDiscount": 0,
        "TyCoupon": 0,
    }
)

# K08, K12: kargo faturası kalem tipleri ve ekstre satırı metinleri.
OUTBOUND_CARGO_ITEM = "Gönderi Kargo Bedeli"
RETURN_CARGO_ITEM = "İade Kargo Bedeli"
CARGO_INVOICE_TEXTS = frozenset({"Kargo Faturası", "Kargo Fatura"})

# K14: `otherfinancials` istek tipleri.
STOPPAGE_TYPE = "Stoppage"
CASH_ADVANCE_TYPE = "CashAdvance"
DEDUCTION_INVOICES_TYPE = "DeductionInvoices"
PLATFORM_SERVICE_FEE_SUBTYPE = "PlatformServiceFee"
# K14: nakit hareketleri gider değildir.
CASH_MOVEMENT_TYPES = frozenset({"PaymentOrder", "WireTransfer", "IncomingTransfer"})
CATEGORY_PENALTY = "ceza"
CATEGORY_EARLY_PAYMENT_FEE = "erken_odeme_bedeli"

# K26: iptal sayılan sipariş durumları.
CANCELLED_STATUSES = frozenset({"Cancelled", "UnSupplied"})

# K08: whoPays=1 satıcı anlaşmalı kargo.
SELLER_PAYS_CARGO = 1
