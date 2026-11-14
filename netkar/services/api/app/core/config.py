"""Uygulama ayarları. Tüm yapılandırma ortam değişkenlerinden okunur."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.crypto import derive_key
from app.core.envelope import KeyRing, KeyRingError
from app.integrations.trendyol.errors import TrendyolConfigError
from app.integrations.trendyol.identity import validate_integrator_name

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class Settings(BaseSettings):
    """Ortam değişkenlerinden okunan ayarlar (önek yok, büyük küçük harf duyarsız)."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Ürün adı tek yerden okunur; marka değişirse yalnız bu ayar değişir.
    product_name: str = "NetKâr"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # Yalnız geliştirme içindir; ENVIRONMENT=prod iken açık olması açılışı engeller.
    debug: bool = False

    # Uygulama rolü (superuser DEĞİL). Migrasyon rolü ayrıdır.
    database_url: str
    database_migration_url: str | None = None
    # Senkron işçisi rolü (netkar_worker): şifreli pazaryeri sütunlarını okuyabilen TEK rol (ADR-0005).
    # Yalnız worker süreci okur; API kullanmaz. Worker için zorunludur (worker_libpq_url).
    worker_database_url: str | None = None

    # AES-256-GCM ana anahtarı: 32 bayt, base64. Repoya girmez.
    data_encryption_key: SecretStr

    # Pazaryeri anahtarları için zarf şifreleme KEK halkası (G05, ADR-0004).
    # DATA_KEKS: virgülle ayrılmış "kid:base64(32 bayt)" listesi; DATA_KEK_ACTIVE: yeni şifrelemede
    # kullanılan kid. Döndürme: yeni kid eklenir, etkin yapılır, `python -m app.tools.rewrap_keys`
    # çalıştırılır, eski kid sonra listeden çıkarılır. prod'da zorunludur; diğer ortamlarda
    # verilmezse DATA_ENCRYPTION_KEY'den türetilen geliştirme KEK'i kullanılır.
    data_keks: SecretStr | None = None
    data_kek_active: str | None = None

    pwned_check_enabled: bool = False
    web_base_url: str = "http://localhost:3000"

    # İstemci IP'si için güvenilir vekil yapılandırması (ADR-0002). Varsayılan: hiçbir vekile
    # güvenilmez, X-Forwarded-For yok sayılır ve bağlantının eş adresi esas alınır.
    # TRUSTED_PROXY_CIDRS: virgülle ayrılmış CIDR listesi (ör. "172.18.0.0/16,10.0.0.0/8").
    # Eş adres bu listedeyse X-Forwarded-For sağdan sola okunur ve listedeki adresler atlanır.
    trusted_proxy_cidrs: Annotated[list[IPNetwork], NoDecode] = Field(default_factory=list)
    # TRUSTED_PROXY_HOPS: sağdan sayılan güvenilir vekil sayısı (bağlantının eş adresi dahil).
    # CIDR listesi verilmişse hop sayısı ek olarak uygulanır; ikisi de boşsa vekil yoktur.
    trusted_proxy_hops: int = Field(0, ge=0, le=10)

    email_backend: Literal["file", "memory"] = "file"
    email_dev_outbox_path: str = "var/outbox.jsonl"

    # Oturum süreleri (saniye)
    session_idle_seconds: int = 12 * 3600
    session_absolute_seconds: int = 30 * 24 * 3600
    reset_token_ttl_minutes: int = 30
    pending_totp_ttl_seconds: int = 300
    trial_days: int = 14

    # Rate limit eşikleri (pencere uzunlukları kodda sabittir)
    rate_limit_login_ip: int = Field(30, ge=1)
    rate_limit_login_email: int = Field(10, ge=1)
    rate_limit_register_ip: int = Field(10, ge=1)
    rate_limit_reset_ip: int = Field(10, ge=1)
    rate_limit_reset_email: int = Field(3, ge=1)
    rate_limit_totp_user: int = Field(10, ge=1)
    rate_limit_totp_ip: int = Field(30, ge=1)

    # TOTP kaba kuvvet koruması: ardışık başarısız deneme eşiği aşılırsa hesap geçici kilitlenir.
    totp_max_failures: int = Field(5, ge=1)
    totp_lock_seconds: int = Field(15 * 60, ge=1)

    # İstek gövdesi üst sınırları (bayt). Auth uç noktaları çok daha küçük gövde bekler.
    max_request_body_bytes: int = Field(1024 * 1024, ge=1)
    max_auth_body_bytes: int = Field(64 * 1024, ge=1)

    # Trendyol istemcisi (ADR-0003). Varsayılan ortam stage; canlıya yalnız açıkça geçilir.
    trendyol_environment: Literal["stage", "live"] = "stage"
    # User-Agent'taki entegratör adı: ASCII harf/rakam, en fazla 30 karakter. Varsayılan ürün kod adı
    # (ürün adı "NetKâr" Türkçe karakter içerdiği için doğrudan kullanılamaz). Geçersizse açılış durur.
    trendyol_integrator_name: str = "NetTablo"
    trendyol_connect_timeout_seconds: float = Field(5.0, gt=0)
    trendyol_read_timeout_seconds: float = Field(20.0, gt=0)
    trendyol_max_retries: int = Field(4, ge=0, le=10)
    trendyol_backoff_base_seconds: float = Field(1.0, gt=0)
    trendyol_backoff_cap_seconds: float = Field(30.0, gt=0)
    # Bağlantı doğrulama isteğin içinde çalışır: Retry-After ve kova beklemesi için toplam bekleme
    # bütçesi (sn) ve toplam son tarih (sn). Aşılırsa 503 "daha sonra deneyin". Senkron işleri
    # bu sınırlara tabi değildir (istemci fabrikasında `max_wait` verilmez).
    trendyol_validation_max_wait_seconds: float = Field(5.0, gt=0)
    trendyol_validation_deadline_seconds: float = Field(15.0, gt=0)
    # Bağlantı ekleme çağrısı Trendyol'a gider: IP ve kiracı başına saatlik deneme sınırı, ayrıca
    # tüm kiracılar için platform geneli dakikalık tavan (tek çıkış IP'sinin itibarını korur).
    rate_limit_marketplace_ip: int = Field(20, ge=1)
    rate_limit_marketplace_tenant: int = Field(10, ge=1)
    rate_limit_marketplace_global_per_minute: int = Field(60, ge=1)
    # /v1/marketplace-accounts gövde üst sınırı (bayt): üç kısa alan beklenir.
    max_marketplace_body_bytes: int = Field(8 * 1024, ge=1)

    # Ürün maliyeti (docs/adr/0005 sonraki tur). İçe aktarma dosyası en fazla 2 MiB; gövde sınırı
    # multipart zarfı için 64 KiB pay içerir (dosyanın kendisi işleyicide ayrıca 2 MiB ile sınırlanır).
    max_cost_import_file_bytes: int = Field(2 * 1024 * 1024, ge=1)
    max_cost_import_body_bytes: int = Field(2 * 1024 * 1024 + 64 * 1024, ge=1)
    # Kiracı başına saatlik sınırlar: içe aktarma (kuru deneme dahil), tekil maliyet yazımı, şablon indirme.
    rate_limit_cost_import_tenant: int = Field(30, ge=1)
    rate_limit_cost_write_tenant: int = Field(600, ge=1)
    rate_limit_cost_template_tenant: int = Field(60, ge=1)
    # Kâr ayarı yazımı (ADR-0006): kiracı başına saatlik sınır (ayrı sayaç anahtarı, maliyetle karışmaz).
    rate_limit_profit_settings_write_tenant: int = Field(600, ge=1)
    # Kâr ayarı okuma uçları (GET profit-settings, /carriers): kiracı başına DAKİKADA istek (ayrı sayaç
    # anahtarı; denetim AD-02). `carriers` her istekte 92 günlük birleştirme sorgusu çalıştırır.
    rate_limit_profit_settings_read_tenant: int = Field(120, ge=1)
    # Kâr raporu uçları (/profit/*): kiracı başına DAKİKADA istek sayısı (her rapor isteği motoru çalıştırır).
    rate_limit_profit_report_tenant: int = Field(60, ge=1)
    # Rapor eşzamanlılık kapısı (denetim S4 Y-01/O-01): beklemez, doluysa 429 (kiracı) ya da 503 (süreç).
    # Her rapor motoru çalıştırır (CPU ve yüzlerce MB bellek); sınırlar süreç içidir (çok süreçte çarpılır).
    profit_report_tenant_concurrency: int = Field(2, ge=1)
    profit_report_process_concurrency: int = Field(4, ge=1)
    profit_report_retry_after_seconds: int = Field(2, ge=1)
    # Dönem sonucu önbelleği (denetim S4 O-01, SU-01): süreç içi, TTL'li, sınırlı LRU. TTL 0 kapatır.
    # Anahtar kiracı, hesap, dönem, ayar sürümü ve veri sürümünü içerir. Bellek: saklanan sonuç ölçülen
    # YAKLAŞIK 4 KB/satırdır; 40.000 satır tavanı SÜREÇ BAŞINA yaklaşık 160 MB eder ve işçi (süreç) sayısıyla
    # ÇARPILIR (motorun hesaplama tepe belleğine ek). Küçük kapsayıcıda tavanı (max_lines) düşürün:
    # tavan_MB ~ max_lines * 4 / 1000 * işçi sayısı. Kiracı başına satır tavanı (tenant_lines, OS-02) tek
    # kiracının tüm önbelleği doldurmasını önler (etkin tavan her zaman en çok max_lines // 4'tür, OK-03:
    # max_lines düşürülse de tek kiracı önbelleği dolduramaz): bu tavanı aşan tek sonuç saklanmaz (yine de
    # eşzamanlı bekleyenlerle paylaşılır). Süresi dolan girdiler her yazımda süpürülür.
    profit_report_cache_ttl_seconds: int = Field(90, ge=0)
    profit_report_cache_max_entries: int = Field(16, ge=1)
    profit_report_cache_max_lines: int = Field(40_000, ge=1)
    profit_report_cache_tenant_entries: int = Field(4, ge=1)
    profit_report_cache_tenant_lines: int = Field(10_000, ge=1)
    # Tek uçuşta bekleyenin üst süre sınırı (OS-10): aşılırsa 503 + Retry-After. Ters vekilin istek zaman
    # aşımından kısa tutulmalıdır.
    profit_report_cache_wait_seconds: float = Field(25.0, gt=0)
    # Hesaplayanın üst süre sınırı (OK-05): takılmış ya da çok yavaş bir hesap bu süreden sonra iptal edilir,
    # tek uçuş kaydı ve kapı yuvası bırakılır, istek 503 + Retry-After (`report-compute-timeout`) alır.
    # Bekleyenin süresinden (wait_seconds) UZUN, ters vekilin istek zaman aşımından KISA olmalıdır (istemci
    # bağlantı kopmadan problem+json görsün). Rapor işleminde `statement_timeout` bundan 5 sn KISA kurulur
    # (`compute - 5 sn`, en az 1 sn; DK-05): veritabanı sınırı önce dolar, temiz 57014 yolu çalışır.
    profit_report_compute_timeout_seconds: float = Field(45.0, gt=0)
    # Ana havuz (istek oturumları): havuz tükenince en çok bu kadar beklenir, sonra 503 + Retry-After.
    # Varsayılan 30 sn kilitlenmeyi büyütüyordu (denetim S4 Y-01).
    db_pool_size: int = Field(10, ge=1)
    db_max_overflow: int = Field(10, ge=0)
    db_pool_timeout_seconds: float = Field(5.0, gt=0)
    db_busy_retry_after_seconds: int = Field(2, ge=1)
    # Hız sınırı sayacının AYRI, küçük havuzu: sayaç yazımı oturum bağlantısı tutulurken ikinci bir
    # bağlantı istemez (tut-ve-bekle kilitlenmesi olmaz). Zaman aşımı kısa; aşımda 503 + Retry-After.
    rate_limit_pool_size: int = Field(5, ge=1)
    rate_limit_pool_timeout_seconds: float = Field(2.0, gt=0)
    rate_limit_busy_retry_after_seconds: int = Field(2, ge=1)
    # XLSX bölüm sınırları (denetim S3 Y-01): açılmış bayt sınırı BÖLÜM başına uygulanır; başlıktaki
    # boyuta güvenilmez, akışta sayılır. Gerekçe: 2 MiB'lik dosyada 10.000 satırlık gerçekçi bir maliyet
    # kitabı styles.xml ~ onlarca KB, sharedStrings.xml ~ 0,5 MB, sayfa ~ 3 MB tutar; sınırlar bunun
    # 10-30 katıdır. XML ağacı bayt başına onlarca kat bellek yer, bu yüzden sınır gevşetilmemelidir.
    cost_import_max_styles_bytes: int = Field(1024 * 1024, ge=1)
    cost_import_max_shared_strings_bytes: int = Field(10 * 1024 * 1024, ge=1)
    cost_import_max_sheet_bytes: int = Field(20 * 1024 * 1024, ge=1)
    cost_import_max_other_part_bytes: int = Field(256 * 1024, ge=1)
    # Okuyucunun AÇMADIĞI bölümler (yazıcı ayarı, tablo, görsel, özel XML, yorum, calcChain vb., YB-02):
    # reddedilmez, yok sayılır; açılmış boyutları bölüm başına bu sınırda ve toplam/oran denetiminde sayılır.
    cost_import_max_ignored_part_bytes: int = Field(1024 * 1024, ge=1)
    # Ayrıştırılan XML bölümlerinde tek başlangıç etiketinin (öznitelik ve xmlns bildirimleri dahil) en çok
    # uzunluğu (YK-04): Excel ve LibreOffice etiketleri birkaç yüz baytı geçmez; 16 KB bol pay bırakır.
    cost_import_max_tag_bytes: int = Field(16 * 1024, ge=64)
    # Öğe sayısı ön taraması (ayrıştırmadan önce): <xf> (stil kaydı) ve <si> (paylaşılan dize).
    cost_import_max_style_xfs: int = Field(10_000, ge=1)
    cost_import_max_shared_strings: int = Field(200_000, ge=1)
    # Akışlı XLSX okuyucu tavanları (denetim S3 YK-01): toplam hücre (10.001 satır x 50 sütun = 500.050),
    # tanınmayan öğe sayısı ve tutulan toplam hücre metni (karakter). Aşımda 422.
    cost_import_max_sheet_cells: int = Field(600_000, ge=1)
    cost_import_max_other_elements: int = Field(50_000, ge=1)
    cost_import_max_text_chars: int = Field(16_000_000, ge=1)
    # Süreç başına eşzamanlı ayrıştırma sayısı ve dolu olduğunda önerilen bekleme (sn). Kiracı başına
    # aynı anda tek içe aktarma vardır. Sayaçlar SÜREÇ İÇİDİR: çok süreçli dağıtımda süreç sayısıyla
    # çarpılır. Sonraki tur (YB-01): çok süreçte kiracı kilidi ve ayrıştırma yuvaları pg_try_advisory_lock'a
    # taşınmalı; yuva sayısı makine belleğine göre süreç sayısıyla bölünmeli.
    cost_import_parse_concurrency: int = Field(2, ge=1)
    cost_import_retry_after_seconds: int = Field(5, ge=1)

    # Eşzamanlı argon2 özet sayısı (her özet ~64 MiB bellek kullanır). Olay döngüsü
    # bloklanmasın diye özetler iş parçacığı havuzunda ve bu sınırla çalışır.
    password_hash_concurrency: int = Field(default_factory=lambda: min(4, os.cpu_count() or 1), ge=1)

    @field_validator("trendyol_integrator_name")
    @classmethod
    def _validate_integrator(cls, value: str) -> str:
        """Geçersiz entegratör adında uygulama açılmaz (istemci kurulamayacağı için)."""
        try:
            return validate_integrator_name(value)
        except TrendyolConfigError as exc:
            raise ValueError(str(exc)) from None

    @model_validator(mode="after")
    def _validate_kek_ring(self) -> Settings:
        """KEK halkası geçerli olmalı; prod'da açıkça verilmeli. İleti anahtar değerini yazmaz."""
        if self.data_keks is None and self.data_kek_active is None:
            if self.environment == "prod":
                raise ValueError("ENVIRONMENT=prod iken DATA_KEKS ve DATA_KEK_ACTIVE zorunludur")
            return self
        if self.data_keks is None or self.data_kek_active is None:
            raise ValueError("DATA_KEKS ve DATA_KEK_ACTIVE birlikte verilmeli")
        try:
            KeyRing.parse(self.data_keks.get_secret_value(), self.data_kek_active)
        except KeyRingError as exc:
            raise ValueError(f"DATA_KEKS/DATA_KEK_ACTIVE geçersiz: {exc}") from None
        return self

    @model_validator(mode="after")
    def _validate_report_timeouts(self) -> Settings:
        """Hesaplama üst sınırı, bekleyenin süresinden uzun olmalı (OK-05): aksi halde bekleyen, hesaplayan
        sınırı aşmadan 503 alır ve takılmış hesap hiç sonlanmazdı."""
        if self.profit_report_compute_timeout_seconds <= self.profit_report_cache_wait_seconds:
            raise ValueError(
                "PROFIT_REPORT_COMPUTE_TIMEOUT_SECONDS, PROFIT_REPORT_CACHE_WAIT_SECONDS "
                "değerinden büyük olmalı"
            )
        return self

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_cidrs(cls, value: object) -> object:
        """Ortam değişkeninden gelen 'a/24, b/16' dizesini CIDR listesine çevirir."""
        if isinstance(value, str):
            return [
                ipaddress.ip_network(part.strip(), strict=False) for part in value.split(",") if part.strip()
            ]
        return value

    @model_validator(mode="after")
    def _reject_unsafe_production(self) -> Settings:
        """Üretimde güvensiz varsayılanlar açılışı durdurur (denetim D-08)."""
        if self.environment == "prod":
            problems: list[str] = []
            if self.email_backend in {"file", "memory"}:
                problems.append("ENVIRONMENT=prod iken EMAIL_BACKEND=file/memory kullanılamaz")
            if self.debug:
                problems.append("ENVIRONMENT=prod iken DEBUG açık olamaz")
            if problems:
                raise ValueError("; ".join(problems))
        return self

    @field_validator("database_url", "database_migration_url", "worker_database_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        """SQLAlchemy için psycopg 3 sürücüsünü zorlar."""
        if value is None:
            return None
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @field_validator("data_encryption_key")
    @classmethod
    def _validate_key(cls, value: SecretStr) -> SecretStr:
        """Anahtar base64 olmalı ve tam 32 bayt çözülmelidir."""
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("DATA_ENCRYPTION_KEY base64 olmalı") from exc
        if len(raw) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY 32 bayt olmalı")
        return value

    @property
    def master_key(self) -> bytes:
        """Çözülmüş 32 baytlık ana anahtar."""
        return base64.b64decode(self.data_encryption_key.get_secret_value())

    @property
    def key_ring(self) -> KeyRing:
        """Pazaryeri sırları için KEK halkası (verilmediyse geliştirme KEK'i, yalnız prod dışı)."""
        if self.data_keks is not None and self.data_kek_active is not None:
            return KeyRing.parse(self.data_keks.get_secret_value(), self.data_kek_active)
        return KeyRing({"dev-derived": derive_key(self.master_key, "kek-dev")}, "dev-derived")

    @property
    def libpq_url(self) -> str:
        """Sürücü ekinden arındırılmış bağlantı dizesi (procrastinate için)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def worker_libpq_url(self) -> str:
        """Worker bağlantı dizesi (procrastinate). WORKER_DATABASE_URL yoksa worker başlamaz.

        Uygulama rolüne geri düşülmez: o rol şifreli sütunları okuyamaz (ADR-0005), sessiz geri
        düşme senkronu çalışır gibi gösterip kimlik bilgisi okurken patlatırdı.
        """
        if self.worker_database_url is None:
            raise ValueError("WORKER_DATABASE_URL tanımlı değil (worker netkar_worker rolüyle bağlanır)")
        return self.worker_database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Süreç boyunca tek ayar nesnesi (testlerde create_app'e açıkça verilir)."""
    return Settings()
