# Alan adı ve marka aday listesi (17 Kasım 2026). Müsaitlik bu oturumdan doğrulanamadı
# (RDAP ve nic.tr ağ kısıtıyla engelli); sütunlar yalnız web aramasındaki ad çakışmasını gösterir.
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASLIK = ["Sıra", "Ad", "Alan adı adayları", "Anlamı", "Güçlü yanı", "Riski", "Web araması 17.11 (ad çakışması)", "Öneri"]
ADAYLAR = [
    ("NetTablo (mevcut)", "nettablo.com, nettablo.com.tr", "Net kâr tablosu; \"net bir tablo\" deyimi", "Karar kayıtlı (K-N01), kodda ve metinlerde kullanılıyor; değişim maliyeti yok", "\"Tablo\" adlı ABD TV kayıt cihazı ve Avustralya yayınevi var (farklı sektör)", "Aynı adla ürün bulunmadı", "1. tercih: müsaitse koru"),
    ("NetMarj", "netmarj.com, netmarj.com.tr", "Net marj (kâr marjı)", "Kısa, ürünün vaadini söylüyor, yazımı kolay", "\"Marj\" tanımlayıcı sözcük; tescilde ayırt edicilik sorgulanabilir", "Aynı adla ürün bulunmadı", "2. tercih"),
    ("KârPusula", "karpusula.com, karpusula.com.tr", "Kâra yön gösteren pusula", "Ayırt edici, akılda kalıcı, uyarı/öneri özelliğini çağrıştırıyor", "Biraz uzun; \"kar\" yazımı kâr/kar (snow) belirsizliği", "Aynı adla ürün bulunmadı", "3. tercih"),
    ("MarjTablo", "marjtablo.com, marjtablo.com.tr", "Marj tablosu", "NetTablo ile aynı aile; geçiş kolay", "İki tanımlayıcı sözcük; tescil riski orta", "Aynı adla ürün bulunmadı", "Yedek"),
    ("KârTablo", "kartablo.com, kartablo.com.tr", "Kâr tablosu", "Ne yaptığını doğrudan söylüyor", "Tanımlayıcı; \"kartablo\" okunuşu belirsiz; tescil riski yüksek", "Aynı adla ürün bulunmadı", "Yedek"),
    ("Marjino", "marjino.com, marjino.com.tr", "Marj + sevimli ek", "Uydurma sözcük, tescil için güçlü, yurt dışında okunur", "Anlamı açıklama ister; çocuksu bulunabilir", "Aynı adla ürün bulunmadı", "Yedek (marka gücü yüksek)"),
    ("Kârsayaç", "karsayac.com, karsayac.com.tr", "Kârı sayan sayaç", "Türkçe, anlaşılır", "Uzun, ş/ç harfleri alan adında düşüyor; yurt dışında zor", "Aynı adla ürün bulunmadı", "Zayıf"),
    ("SafiKâr", "safikar.com, safikar.com.tr", "Safi (net) kâr", "Türkçe ve anlamlı (önceki aday listesinden)", "\"safikar\" okunuşu belirsiz; tanımlayıcı", "Aynı adla ürün bulunmadı", "Zayıf"),
    ("KârBak", "karbak.com, karbak.com.tr", "Kâra bak", "Kısa, eylem çağrısı (önceki aday listesinden)", "\"karbak\" yazımı anlamsız okunabilir", "Bu turda aranmadı", "Zayıf"),
    ("NetKazanç", "netkazanc.com, netkazanc.com.tr", "Net kazanç", "Herkesin anladığı terim", "Jenerik; tescil reddi riski yüksek", "Bu turda aranmadı", "Önerilmez"),
]
NOTLAR = [
    "Müsaitlik doğrulanmadı: RDAP (Verisign) ve nic.tr bu oturumda ağ kısıtıyla engelli. Hasan sorgulamalı.",
    "Alan adında Türkçe karakter (â, ş, ç) kullanılmaz; IDN alan adı önerilmez.",
    "Her aday için .com ve .com.tr birlikte alınmalı; marka adı ile alan adı aynı olmalı.",
    "Tescil: marka vekiliyle TÜRKPATENT ön araştırması, 9. sınıf (yazılım) ve 42. sınıf (SaaS).",
    "\"Seller\" ile başlayan adlardan kaçın: SellerIQ adlı Trendyol kâr hesaplayıcı eklentisi var.",
    "\"Funnel\" ile başlayan adlar önerilmez (FunnelMates ve tescilli Funnel- markaları).",
    "Alan adı alımı ve tescil masrafı Hasan onayıyla yapılır; bu listede hiçbir hesap açılmadı.",
]
wb = Workbook(); ws = wb.active; ws.title = "Adaylar"
ws.append(BASLIK)
for i, a in enumerate(ADAYLAR, 1):
    ws.append([i, *a])
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F4E79")
for row in ws.iter_rows(min_row=2):
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical="top")
for i, w in enumerate([6, 18, 30, 26, 34, 38, 28, 22], 1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A2"
n = wb.create_sheet("Notlar")
n.append(["Not"]); n["A1"].font = Font(bold=True)
for t in NOTLAR:
    n.append([t])
n.column_dimensions["A"].width = 110
wb.save("/home/user/hyt/netkar/calisma_dosyalari/alan_adi_adaylari_2026-11-17.xlsx")
print(len(ADAYLAR), "aday yazıldı")
