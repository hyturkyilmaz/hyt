# HYT Content Automation — WordPress Plugin v1.0.0

**Geliştirici:** Claude (Anthropic) · Mayıs 2026  
**Proje:** hyturkyilmaz/hyt  
**Branch:** `claude/hyt-content-automation-plugin-PrdPB`

---

## Oturum Özeti

Bu oturumda Hasan Yasin Türkyılmaz için tam işlevsel bir WordPress eklentisi sıfırdan geliştirildi.

### Ne İstendi

- Google Drive'dan veya manuel olarak 200–300 adet `.docx` dosyası yükleme
- Her yazının WordPress'te daha önce yayınlanıp yayınlanmadığını kontrol etme (duplicate tespiti)
- Yayınlanmışsa uyarı verme, yayınlanmamışsa Claude API ile SEO/GEO optimizasyonu yapma
- Her gün 08:45'te bir yazı yayına girecek şekilde akıllı zamanlama
- WordPress admin panelinde kuyruk yönetimi, loglar ve ayarlar sayfası

### Ne Yapıldı

1. **Teknik brief analiz edildi** — v2.0.0 dokümantasyonu incelenerek v1 kapsamı belirlendi
2. **16 dosyadan oluşan tam plugin yazıldı** — PHP 8.1+, WordPress 6.2+ uyumlu
3. **ZIP paketi oluşturuldu** — `hyt-content-automation-v1.0.0.zip` (44 KB)
4. **Masaüstüne kopyalandı** — `/root/Desktop/hyt-content-automation-v1.0.0.zip`
5. **Git commit yapıldı** — 4 commit, push için GitHub token yetkisi bekleniyor

---

## Dosya Yapısı

```
plugin/
├── hyt-content-automation.php              # Ana plugin (97 satır)
├── includes/
│   ├── class-database.php                  # DB kurulum + CRUD (214 satır)
│   ├── class-scheduler.php                 # WP Cron + akıllı slot (166 satır)
│   ├── class-logger.php                    # Yapılandırılmış loglama (90 satır)
│   ├── class-duplicate-checker.php         # Yinelenen içerik tespiti (141 satır)
│   ├── api/
│   │   ├── class-claude.php                # Claude API SEO/GEO (202 satır)
│   │   └── class-google-drive.php          # Google Drive OAuth2 (431 satır)
│   ├── pipeline/
│   │   └── class-content-pipeline.php      # Ana pipeline (305 satır)
│   └── admin/
│       ├── class-admin-menu.php            # Admin menü (145 satır)
│       └── class-ajax.php                  # 13 AJAX handler (466 satır)
└── admin/
    ├── views/
    │   ├── dashboard.php                   # Dashboard (203 satır)
    │   ├── queue.php                       # Kuyruk sayfası (183 satır)
    │   ├── logs.php                        # Log görüntüleyici (103 satır)
    │   └── settings.php                    # Ayarlar (324 satır)
    ├── css/style.css                       # WP native stil (588 satır)
    └── js/main.js                          # Drag-drop + AJAX UI (524 satır)

Toplam: 16 dosya · ~3.400 satır kod
```

---

## Veritabanı

### `wp_hyt_pipeline`
| Sütun | Tip | Açıklama |
|-------|-----|----------|
| id | BIGINT | Otomatik artan PK |
| source | ENUM | `manual` veya `gdrive` |
| file_name | VARCHAR(500) | Yüklenen dosya adı |
| original_title | VARCHAR(500) | İçerikten çıkarılan başlık |
| post_id | BIGINT | Oluşturulan WP post ID |
| status | ENUM | `pending/processing/duplicate/scheduled/published/failed/cancelled` |
| step | VARCHAR(100) | Mevcut pipeline adımı |
| word_count | INT | Kelime sayısı |
| seo_data | LONGTEXT | Claude'dan dönen JSON (SEO verileri) |
| raw_content | LONGTEXT | Ham dosya içeriği |
| processed_content | LONGTEXT | SEO optimize edilmiş HTML |
| scheduled_at | DATETIME | Yayın tarihi |
| error_message | TEXT | Hata mesajı |

### `wp_hyt_logs`
| Sütun | Tip | Açıklama |
|-------|-----|----------|
| id | BIGINT | PK |
| pipeline_id | BIGINT | İlgili pipeline |
| level | ENUM | `info/warning/error` |
| context | VARCHAR(100) | `claude/gdrive/pipeline/upload/scheduler` |
| message | TEXT | Log mesajı |
| data | LONGTEXT | JSON ek veri |

---

## Pipeline Akışı

```
Dosya Yükleme (.docx / .txt)
         ↓
   İçerik Ayrıştırma
   (ZipArchive + DOMDocument)
         ↓
   Duplicate Kontrolü ──→ YINELENEN: status=duplicate, uyarı göster
         ↓ (yeni içerik)
   Claude API SEO/GEO ──→ API yoksa ham içerik kullanılır
         ↓
   Akıllı Slot Bulma
   (08:45, dolu günleri atla, tatilleri atla)
         ↓
   WP Post Oluştur (status=future)
   + Yoast SEO meta
   + FAQ Schema meta
         ↓
   status=scheduled ✓
```

---

## Kurulum

### 1. WordPress'e Yükleme
**Eklentiler → Yeni Ekle → Eklenti Yükle** → `hyt-content-automation-v1.0.0.zip` → **Yükle → Etkinleştir**

### 2. İlk Yapılandırma Sırası
1. **Ayarlar → API Anahtarları** → Claude API Key gir → Test Et
2. **Ayarlar → Yayın Planı** → Günler, saat (08:45), yazar, kategori
3. **Ayarlar → Google Drive** (opsiyonel) → Client ID/Secret → Bağlan
4. **Ayarlar → Tatil Günleri** → Tarihleri kontrol et

### 3. Kullanım
- Dashboard'a git → Dosyaları sürükle-bırak → "Yükle ve İşle"
- Her dosya otomatik olarak: ayrıştırılır → duplicate kontrolünden geçer → Claude ile optimize edilir → uygun güne planlanır

---

## Ayarlar Referansı

| WP Option | Varsayılan | Açıklama |
|-----------|-----------|----------|
| `hyt_claude_api_key` | — | Claude API key (`sk-ant-...`) |
| `hyt_claude_model` | `claude-sonnet-4-5` | Kullanılacak model |
| `hyt_gdrive_client_id` | — | Google OAuth Client ID |
| `hyt_gdrive_client_secret` | — | Google OAuth Client Secret |
| `hyt_gdrive_folder_id` | — | Drive klasör ID |
| `hyt_gdrive_frequency` | `1hour` | Tarama sıklığı |
| `hyt_schedule_time` | `08:45` | Günlük yayın saati |
| `hyt_schedule_days` | Tüm günler | İzin verilen günler (0=Paz..6=Cmt) |
| `hyt_schedule_author` | `1` | Yazar kullanıcı ID |
| `hyt_schedule_category` | `0` | Kategori term ID |
| `hyt_holiday_dates` | `[]` | JSON tarih dizisi `["2026-01-01"]` |

---

## Duplicate Tespiti

3 katmanlı kontrol:

1. **Tam başlık eşleşmesi** — `post_title = ?` SQL sorgusu
2. **Benzer başlık** — PHP `similar_text()` ile son 1000 post taranır, %80+ eşleşme yinelenen sayılır
3. **Slug eşleşmesi** — `post_name = sanitize_title(başlık)`

Yinelenen tespit edilirse `status=duplicate` atanır, kuyrukta sarı badge ile gösterilir. "Tekrar İşle" butonu ile override edilebilir.

---

## Claude API Entegrasyonu

**Endpoint:** `POST https://api.anthropic.com/v1/messages`  
**Timeout:** 180 saniye  
**Desteklenen modeller:** `claude-opus-4-5` / `claude-sonnet-4-5` / `claude-haiku-4-5`

Claude'dan dönen JSON yapısı:
```json
{
  "seo_title": "50-60 karakter SEO başlığı",
  "slug": "url-dostu-slug",
  "meta_description": "max 155 karakter meta açıklaması",
  "focus_keyword": "ana anahtar kelime",
  "secondary_keywords": ["ikincil", "kelimeler"],
  "faq_schema": [
    {"question": "Soru?", "answer": "Cevap"}
  ],
  "geo_summary": "AI arama motorları için yetkili özet",
  "optimized_content": "<h2>HTML...</h2><p>optimize içerik</p>"
}
```

**Yoast SEO uyumu:** `_yoast_wpseo_title`, `_yoast_wpseo_metadesc`, `_yoast_wpseo_focuskw` meta alanları otomatik doldurulur.

**Claude yoksa:** Ham içerik orijinal başlıkla planlanır, sonradan optimize edilebilir.

---

## Akıllı Zamanlayıcı

`Scheduler::find_next_slot()` şu mantıkla çalışır:

```
1. Bugün 08:45 geçtiyse → yarından başla
2. O günün haftanın izin verilen günü olup olmadığını kontrol et
3. Tatil günü mü kontrol et (wp_options: hyt_holiday_dates)
4. O tarihte WP future post var mı kontrol et
5. O tarihte pipeline'da scheduled kayıt var mı kontrol et
6. Slot boşsa → bu günü döndür
7. Doluysa → +1 gün, başa dön
```

WP Cron her 5 dakikada bir `hyt_process_queue` hook'unu tetikler, en fazla 10 pending öğeyi sırayla işler.

---

## Admin Panel

### Dashboard
- 6 istatistik kartı (Toplam / Bekliyor+İşleniyor / Planlandı / Başarısız / Yinelenen / Yayında)
- Drag-drop yükleme alanı (300 dosyaya kadar, 50'lik batch'ler halinde XHR upload)
- Google Drive tarama butonu
- Son 20 işlem tablosu

### Kuyruk Sayfası
- 7 filtre sekmesi (Tümü / Bekliyor / İşleniyor / Yinelenen / Planlandı / Yayında / Başarısız)
- Her satırda: Tekrar İşle / WP Post Düzenle / İptal Et butonları
- "Tüm Başarısızları Tekrar Dene" toplu butonu
- 30 kayıt/sayfa sayfalama

### Loglar
- Seviye filtreleri: Tümü / Bilgi / Uyarı / Hata
- 50 kayıt/sayfa
- Hata satırları kırmızı, uyarılar sarı arka plan

### Ayarlar (4 Sekme)
- **API Anahtarları:** Claude key + model seçimi + test butonu
- **Google Drive:** OAuth2 kurulumu + klasör ID + tarama sıklığı
- **Yayın Planı:** Günler + saat + yazar + kategori
- **Tatil Günleri:** JSON editör + 2026 Türkiye tatil listesi

---

## AJAX Endpoints

Tüm endpointler `hyt_ajax_nonce` nonce + `manage_options` capability kontrolü yapar.

| Action | Açıklama |
|--------|----------|
| `hyt_upload_files` | Dosya yükleme ve pipeline başlatma |
| `hyt_process_item` | Tek öğeyi manuel işle |
| `hyt_retry_item` | Başarısız öğeyi tekrar dene |
| `hyt_cancel_item` | İptal et (varsa WP post'u çöpe taşır) |
| `hyt_get_queue` | Sayfalı kuyruk verisi |
| `hyt_get_stats` | İstatistik sayıları |
| `hyt_test_claude` | Claude API bağlantı testi |
| `hyt_save_settings` | Ayarları kaydet (tab bazlı) |
| `hyt_gdrive_scan` | Drive klasörünü tara |
| `hyt_gdrive_connect` | OAuth URL döndür |
| `hyt_gdrive_disconnect` | Token sil |
| `hyt_retry_all_failed` | Tüm başarısızları tekrar kuyruğa al |
| `hyt_get_logs` | Sayfalı log verisi |

---

## Kaynak Kod

---

### `plugin/hyt-content-automation.php`

```php
<?php
/**
 * Plugin Name: HYT Content Automation
 * Plugin URI:  https://hyt.com.tr
 * Description: Toplu .docx yükleme, Google Drive entegrasyonu, Claude API SEO optimizasyonu ve akıllı zamanlama ile içerik otomasyonu.
 * Version:     1.0.0
 * Author:      HYT
 * Author URI:  https://hyt.com.tr
 * License:     GPL-2.0+
 * Requires at least: 6.2
 * Requires PHP: 8.1
 * Text Domain: hyt-content-automation
 */

declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'HYT_VERSION', '1.0.0' );
define( 'HYT_PLUGIN_FILE', __FILE__ );
define( 'HYT_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'HYT_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'HYT_PLUGIN_BASENAME', plugin_basename( __FILE__ ) );

spl_autoload_register( function ( string $class_name ): void {
    $prefix = 'HYT\\';
    if ( ! str_starts_with( $class_name, $prefix ) ) {
        return;
    }
    $relative = substr( $class_name, strlen( $prefix ) );
    $parts    = explode( '\\', $relative );
    $file     = 'class-' . strtolower( str_replace( '_', '-', array_pop( $parts ) ) ) . '.php';
    $dir      = strtolower( implode( DIRECTORY_SEPARATOR, $parts ) );
    $path = HYT_PLUGIN_DIR . 'includes' . ( $dir ? DIRECTORY_SEPARATOR . $dir : '' ) . DIRECTORY_SEPARATOR . $file;
    if ( file_exists( $path ) ) {
        require_once $path;
    }
} );

register_activation_hook( __FILE__, function (): void {
    require_once HYT_PLUGIN_DIR . 'includes/class-database.php';
    HYT\Database::create_tables();
    HYT\Scheduler::register_cron();
    flush_rewrite_rules();
} );

register_deactivation_hook( __FILE__, function (): void {
    wp_clear_scheduled_hook( 'hyt_process_queue' );
    flush_rewrite_rules();
} );

add_action( 'plugins_loaded', function (): void {
    HYT\Database::create_tables();
    HYT\Scheduler::register_cron();
    if ( is_admin() ) {
        ( new HYT\Admin\Admin_Menu() )->init();
        ( new HYT\Admin\Ajax() )->init();
    }
    add_action( 'rest_api_init', function (): void {
        register_rest_route( 'hyt/v1', '/gdrive-callback', [
            'methods'             => 'GET',
            'callback'            => [ HYT\Api\Google_Drive::class, 'handle_oauth_callback' ],
            'permission_callback' => '__return_true',
        ] );
    } );
} );

add_action( 'hyt_process_queue', function (): void {
    HYT\Scheduler::process_queue();
} );
```

---

### `includes/class-database.php`

```php
<?php
declare(strict_types=1);
namespace HYT;
if ( ! defined( 'ABSPATH' ) ) { exit; }

class Database {

    public static function create_tables(): void {
        global $wpdb;
        $charset_collate = $wpdb->get_charset_collate();
        $db_version      = get_option( 'hyt_db_version', '0' );
        if ( version_compare( $db_version, '1.0.0', '>=' ) ) { return; }
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        $pipeline_table = $wpdb->prefix . 'hyt_pipeline';
        $logs_table     = $wpdb->prefix . 'hyt_logs';
        $sql_pipeline = "CREATE TABLE {$pipeline_table} (
            id           BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
            source       ENUM('manual','gdrive') NOT NULL DEFAULT 'manual',
            file_name    VARCHAR(500) NOT NULL DEFAULT '',
            original_title VARCHAR(500) NOT NULL DEFAULT '',
            post_id      BIGINT(20) UNSIGNED NULL DEFAULT NULL,
            status       ENUM('pending','processing','duplicate','scheduled','published','failed','cancelled') NOT NULL DEFAULT 'pending',
            step         VARCHAR(100) NOT NULL DEFAULT '',
            word_count   INT(11) NOT NULL DEFAULT 0,
            seo_data     LONGTEXT NULL DEFAULT NULL,
            raw_content  LONGTEXT NULL DEFAULT NULL,
            processed_content LONGTEXT NULL DEFAULT NULL,
            scheduled_at DATETIME NULL DEFAULT NULL,
            error_message TEXT NULL DEFAULT NULL,
            created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_status (status),
            KEY idx_scheduled_at (scheduled_at),
            KEY idx_post_id (post_id)
        ) {$charset_collate};";
        $sql_logs = "CREATE TABLE {$logs_table} (
            id          BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
            pipeline_id BIGINT(20) UNSIGNED NULL DEFAULT NULL,
            level       ENUM('error','warning','info') NOT NULL DEFAULT 'info',
            context     VARCHAR(100) NOT NULL DEFAULT '',
            message     TEXT NOT NULL,
            data        LONGTEXT NULL DEFAULT NULL,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_pipeline_id (pipeline_id),
            KEY idx_level (level),
            KEY idx_created_at (created_at)
        ) {$charset_collate};";
        dbDelta( $sql_pipeline );
        dbDelta( $sql_logs );
        update_option( 'hyt_db_version', '1.0.0' );
    }

    public static function get_pipeline_table(): string { global $wpdb; return $wpdb->prefix . 'hyt_pipeline'; }
    public static function get_logs_table(): string { global $wpdb; return $wpdb->prefix . 'hyt_logs'; }

    public static function get_stats(): array {
        global $wpdb;
        $table = self::get_pipeline_table();
        $rows  = $wpdb->get_results( "SELECT status, COUNT(*) as cnt FROM {$table} GROUP BY status", ARRAY_A );
        $stats = [ 'total' => 0, 'pending' => 0, 'processing' => 0, 'duplicate' => 0, 'scheduled' => 0, 'published' => 0, 'failed' => 0, 'cancelled' => 0 ];
        foreach ( $rows as $row ) { $stats[ $row['status'] ] = (int) $row['cnt']; $stats['total'] += (int) $row['cnt']; }
        return $stats;
    }

    public static function insert_pipeline( array $data ): int|false {
        global $wpdb;
        $data['created_at'] = current_time( 'mysql' );
        $data['updated_at'] = current_time( 'mysql' );
        $result = $wpdb->insert( self::get_pipeline_table(), $data );
        return false === $result ? false : (int) $wpdb->insert_id;
    }

    public static function update_pipeline( int $id, array $data ): void {
        global $wpdb;
        $data['updated_at'] = current_time( 'mysql' );
        $wpdb->update( self::get_pipeline_table(), $data, [ 'id' => $id ] );
    }

    public static function get_pipeline_item( int $id ): ?object {
        global $wpdb;
        $table = self::get_pipeline_table();
        return $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) );
    }

    public static function get_pipeline_items( array $args = [] ): array {
        global $wpdb;
        $table    = self::get_pipeline_table();
        $defaults = [ 'status' => '', 'per_page' => 30, 'page' => 1, 'orderby' => 'created_at', 'order' => 'DESC' ];
        $args     = wp_parse_args( $args, $defaults );
        $offset   = ( (int) $args['page'] - 1 ) * (int) $args['per_page'];
        $orderby  = sanitize_sql_orderby( $args['orderby'] . ' ' . $args['order'] ) ?: 'created_at DESC';
        $where    = ''; $params = [];
        if ( ! empty( $args['status'] ) && 'all' !== $args['status'] ) { $where = 'WHERE status = %s'; $params[] = $args['status']; }
        $total    = (int) $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$table} {$where}", ...$params ) );
        $params[] = (int) $args['per_page']; $params[] = $offset;
        $items    = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} {$where} ORDER BY {$orderby} LIMIT %d OFFSET %d", ...$params ) );
        return [ 'items' => $items ?: [], 'total' => $total ];
    }

    public static function get_recent_items( int $limit = 20 ): array {
        global $wpdb;
        $table = self::get_pipeline_table();
        return $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} ORDER BY created_at DESC LIMIT %d", $limit ) ) ?: [];
    }
}
```

---

### `includes/class-scheduler.php`

```php
<?php
declare(strict_types=1);
namespace HYT;
if ( ! defined( 'ABSPATH' ) ) { exit; }

class Scheduler {

    public static function register_cron(): void {
        add_filter( 'cron_schedules', function ( array $schedules ): array {
            if ( ! isset( $schedules['hyt_five_minutes'] ) ) {
                $schedules['hyt_five_minutes'] = [ 'interval' => 300, 'display' => 'Her 5 dakika' ];
            }
            return $schedules;
        } );
        if ( ! wp_next_scheduled( 'hyt_process_queue' ) ) {
            wp_schedule_event( time(), 'hyt_five_minutes', 'hyt_process_queue' );
        }
    }

    public static function find_next_slot(): \DateTime {
        $slot_time     = get_option( 'hyt_schedule_time', '08:45' );
        $allowed_days  = get_option( 'hyt_schedule_days', [ '1','2','3','4','5','6','0' ] );
        $holiday_dates = [];
        $holidays_raw  = get_option( 'hyt_holiday_dates', '' );
        if ( $holidays_raw ) {
            $decoded = json_decode( $holidays_raw, true );
            if ( is_array( $decoded ) ) $holiday_dates = $decoded;
        }
        $taken           = self::get_scheduled_dates();
        [$hour, $minute] = array_map( 'intval', explode( ':', $slot_time ) );
        $start           = new \DateTime( 'now', wp_timezone() );
        $start->setTime( $hour, $minute, 0 );
        $now             = new \DateTime( 'now', wp_timezone() );
        if ( $start <= $now ) $start->modify( '+1 day' );
        for ( $i = 0; $i < 365; $i++ ) {
            $dow      = $start->format( 'w' );
            $date_str = $start->format( 'Y-m-d' );
            if ( ! in_array( (string) $dow, (array) $allowed_days, true ) ) { $start->modify( '+1 day' ); continue; }
            if ( in_array( $date_str, $holiday_dates, true ) ) { $start->modify( '+1 day' ); continue; }
            $slot_dt = $date_str . ' ' . sprintf( '%02d:%02d:00', $hour, $minute );
            if ( ! in_array( $slot_dt, $taken, true ) ) return $start;
            $start->modify( '+1 day' );
        }
        return $start;
    }

    public static function get_scheduled_dates(): array {
        global $wpdb;
        $slot_time    = get_option( 'hyt_schedule_time', '08:45' );
        [$hour, $min] = array_map( 'intval', explode( ':', $slot_time ) );
        $time_suffix  = sprintf( ' %02d:%02d:00', $hour, $min );
        $wp_dates     = $wpdb->get_col( "SELECT DATE_FORMAT(post_date, '%Y-%m-%d') FROM {$wpdb->posts} WHERE post_status = 'future'" );
        $pt           = Database::get_pipeline_table();
        $pl_dates     = $wpdb->get_col( "SELECT DATE_FORMAT(scheduled_at, '%Y-%m-%d') FROM {$pt} WHERE scheduled_at IS NOT NULL AND status IN ('scheduled','processing','pending')" );
        $taken        = [];
        foreach ( array_merge( (array) $wp_dates, (array) $pl_dates ) as $date ) {
            if ( $date ) $taken[] = $date . $time_suffix;
        }
        return array_unique( $taken );
    }

    public static function process_queue(): void {
        global $wpdb;
        $table = Database::get_pipeline_table();
        $items = $wpdb->get_results( $wpdb->prepare( "SELECT id FROM {$table} WHERE status = 'pending' ORDER BY created_at ASC LIMIT %d", 10 ) );
        if ( empty( $items ) ) return;
        $pipeline = new Pipeline\Content_Pipeline();
        foreach ( $items as $item ) {
            try {
                $pipeline->process( (int) $item->id );
            } catch ( \Throwable $e ) {
                Logger::error( 'Hata: ' . $e->getMessage(), 'scheduler', null, (int) $item->id );
                Database::update_pipeline( (int) $item->id, [ 'status' => 'failed', 'error_message' => $e->getMessage() ] );
            }
        }
    }
}
```

---

### `includes/class-logger.php`

```php
<?php
declare(strict_types=1);
namespace HYT;
if ( ! defined( 'ABSPATH' ) ) { exit; }

class Logger {
    public static function info( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void { self::log( 'info', $message, $context, $data, $pipeline_id ); }
    public static function warning( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void { self::log( 'warning', $message, $context, $data, $pipeline_id ); }
    public static function error( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void { self::log( 'error', $message, $context, $data, $pipeline_id ); }

    private static function log( string $level, string $message, string $context, mixed $data, ?int $pipeline_id ): void {
        global $wpdb;
        $wpdb->insert( Database::get_logs_table(), [
            'pipeline_id' => $pipeline_id,
            'level'       => $level,
            'context'     => substr( $context, 0, 100 ),
            'message'     => $message,
            'data'        => $data !== null ? wp_json_encode( $data ) : null,
            'created_at'  => current_time( 'mysql' ),
        ] );
    }

    public static function get_logs( array $args = [] ): array {
        global $wpdb;
        $table    = Database::get_logs_table();
        $defaults = [ 'level' => '', 'pipeline_id' => null, 'per_page' => 50, 'page' => 1 ];
        $args     = wp_parse_args( $args, $defaults );
        $offset   = ( (int) $args['page'] - 1 ) * (int) $args['per_page'];
        $wheres   = []; $params = [];
        if ( ! empty( $args['level'] ) ) { $wheres[] = 'level = %s'; $params[] = $args['level']; }
        if ( ! empty( $args['pipeline_id'] ) ) { $wheres[] = 'pipeline_id = %d'; $params[] = (int) $args['pipeline_id']; }
        $where       = $wheres ? 'WHERE ' . implode( ' AND ', $wheres ) : '';
        $count_params = $params;
        $total        = (int) $wpdb->get_var( $wpdb->prepare( "SELECT COUNT(*) FROM {$table} {$where}", ...$count_params ) );
        $params[] = (int) $args['per_page']; $params[] = $offset;
        $items    = $wpdb->get_results( $wpdb->prepare( "SELECT * FROM {$table} {$where} ORDER BY created_at DESC LIMIT %d OFFSET %d", ...$params ) ) ?: [];
        return [ 'items' => $items, 'total' => $total ];
    }
}
```

---

### `includes/class-duplicate-checker.php`

```php
<?php
declare(strict_types=1);
namespace HYT;
if ( ! defined( 'ABSPATH' ) ) { exit; }

class Duplicate_Checker {

    private const TITLE_SIMILARITY_THRESHOLD = 80;

    public function check( string $title, string $content ): array {
        $result = [ 'is_duplicate' => false, 'match_type' => '', 'matched_post' => null, 'similarity' => 0 ];
        $exact  = $this->exact_title_match( $title );
        if ( $exact ) return array_merge( $result, [ 'is_duplicate' => true, 'match_type' => 'exact_title', 'matched_post' => $exact, 'similarity' => 100 ] );
        $similar = $this->similar_title_match( $title );
        if ( $similar ) return array_merge( $result, [ 'is_duplicate' => true, 'match_type' => 'similar_title', 'matched_post' => $similar['post'], 'similarity' => $similar['percent'] ] );
        $slug_match = $this->slug_match( sanitize_title( $title ) );
        if ( $slug_match ) return array_merge( $result, [ 'is_duplicate' => true, 'match_type' => 'slug_match', 'matched_post' => $slug_match, 'similarity' => 100 ] );
        return $result;
    }

    private function exact_title_match( string $title ): ?\WP_Post {
        global $wpdb;
        $post_id = $wpdb->get_var( $wpdb->prepare(
            "SELECT ID FROM {$wpdb->posts} WHERE post_title = %s AND post_status IN ('publish','future','draft','pending','private') AND post_type = 'post' LIMIT 1", $title
        ) );
        return $post_id ? get_post( (int) $post_id ) : null;
    }

    private function similar_title_match( string $title ): ?array {
        global $wpdb;
        $posts       = $wpdb->get_results( "SELECT ID, post_title FROM {$wpdb->posts} WHERE post_status IN ('publish','future','draft','pending','private') AND post_type = 'post' ORDER BY ID DESC LIMIT 1000" );
        $title_lower = mb_strtolower( $title );
        foreach ( $posts as $post ) {
            $percent = 0;
            similar_text( $title_lower, mb_strtolower( $post->post_title ), $percent );
            if ( $percent >= self::TITLE_SIMILARITY_THRESHOLD ) {
                return [ 'post' => get_post( (int) $post->ID ), 'percent' => (int) round( $percent ) ];
            }
        }
        return null;
    }

    private function slug_match( string $slug ): ?\WP_Post {
        global $wpdb;
        $post_id = $wpdb->get_var( $wpdb->prepare(
            "SELECT ID FROM {$wpdb->posts} WHERE post_name = %s AND post_status IN ('publish','future','draft','pending','private') AND post_type = 'post' LIMIT 1", $slug
        ) );
        return $post_id ? get_post( (int) $post_id ) : null;
    }
}
```

---

### `includes/api/class-claude.php`

```php
<?php
declare(strict_types=1);
namespace HYT\Api;
use HYT\Logger;
if ( ! defined( 'ABSPATH' ) ) { exit; }

class Claude {

    private string $api_key;
    private string $model;
    private string $api_url = 'https://api.anthropic.com/v1/messages';

    public function __construct() {
        $this->api_key = (string) get_option( 'hyt_claude_api_key', '' );
        $this->model   = (string) get_option( 'hyt_claude_model', 'claude-sonnet-4-5' );
    }

    public function is_configured(): bool { return ! empty( $this->api_key ); }

    public function optimize_for_seo( string $title, string $content ): ?array {
        if ( ! $this->is_configured() ) return null;
        $excerpt = mb_substr( $content, 0, 3000 );
        $prompt  = <<<PROMPT
Aşağıdaki makale başlığı ve içeriği için SEO/GEO optimizasyonu yapman gerekiyor.

BAŞLIK: {$title}

İÇERİK (ilk 3000 karakter):
{$excerpt}

GÖREV: Aşağıdaki JSON yapısında yanıt ver. SADECE geçerli JSON döndür, başka hiçbir şey yazma.

{
  "seo_title": "SEO uyumlu başlık (50-60 karakter arası)",
  "slug": "url-dostu-slug-tire-ile-ayrilmis",
  "meta_description": "Arama sonuçlarında görünecek meta açıklaması (maksimum 155 karakter)",
  "focus_keyword": "Ana odak anahtar kelimesi",
  "secondary_keywords": ["ikincil", "anahtar", "kelimeler"],
  "faq_schema": [
    {"question": "Soru 1?", "answer": "Cevap 1"},
    {"question": "Soru 2?", "answer": "Cevap 2"}
  ],
  "geo_summary": "GEO için 2-3 cümlelik yetkili özet",
  "optimized_content": "HTML formatında optimize edilmiş içerik. H2/H3 başlıklar, paragraflar, listeler."
}

Kurallar:
- seo_title kesinlikle 50-60 karakter arası olmalı
- meta_description kesinlikle 155 karakteri geçmemeli
- slug sadece küçük harf, rakam ve tire içermeli
- Tüm metin Türkçe olmalı
PROMPT;
        $response = wp_remote_post( $this->api_url, [
            'timeout' => 180,
            'headers' => [ 'Content-Type' => 'application/json', 'x-api-key' => $this->api_key, 'anthropic-version' => '2023-06-01' ],
            'body'    => wp_json_encode( [ 'model' => $this->model, 'max_tokens' => 4096, 'messages' => [ [ 'role' => 'user', 'content' => $prompt ] ] ] ),
        ] );
        if ( is_wp_error( $response ) ) { Logger::error( 'Claude API hatası: ' . $response->get_error_message(), 'claude_api' ); return null; }
        $http_code = wp_remote_retrieve_response_code( $response );
        $raw_body  = wp_remote_retrieve_body( $response );
        if ( $http_code !== 200 ) { Logger::error( "Claude API HTTP {$http_code}", 'claude_api', [ 'response' => $raw_body ] ); return null; }
        $data = json_decode( $raw_body, true );
        if ( ! isset( $data['content'][0]['text'] ) ) { Logger::error( 'Claude API beklenmeyen format', 'claude_api' ); return null; }
        $text     = $data['content'][0]['text'];
        $seo_data = json_decode( $this->extract_json( $text ), true );
        if ( ! is_array( $seo_data ) ) { Logger::error( 'Claude JSON parse hatası', 'claude_api', [ 'text' => $text ] ); return null; }
        return $seo_data;
    }

    public function test_connection(): array {
        if ( ! $this->is_configured() ) return [ 'success' => false, 'message' => 'API anahtarı girilmemiş.' ];
        $response  = wp_remote_post( $this->api_url, [
            'timeout' => 30,
            'headers' => [ 'Content-Type' => 'application/json', 'x-api-key' => $this->api_key, 'anthropic-version' => '2023-06-01' ],
            'body'    => wp_json_encode( [ 'model' => $this->model, 'max_tokens' => 50, 'messages' => [ [ 'role' => 'user', 'content' => 'Test. Sadece "OK" yaz.' ] ] ] ),
        ] );
        if ( is_wp_error( $response ) ) return [ 'success' => false, 'message' => $response->get_error_message() ];
        $http_code = wp_remote_retrieve_response_code( $response );
        if ( $http_code === 200 ) return [ 'success' => true, 'message' => 'Bağlantı başarılı! Model: ' . $this->model ];
        $body = json_decode( wp_remote_retrieve_body( $response ), true );
        return [ 'success' => false, 'message' => $body['error']['message'] ?? "HTTP {$http_code}" ];
    }

    private function extract_json( string $text ): string {
        if ( preg_match( '/```(?:json)?\s*(\{.*?\})\s*```/s', $text, $matches ) ) return $matches[1];
        if ( preg_match( '/\{.*\}/s', $text, $matches ) ) return $matches[0];
        return $text;
    }
}
```

---

### `includes/api/class-google-drive.php`

_(431 satır — tam kaynak: `plugin/includes/api/class-google-drive.php`)_

**Temel özellikler:**
- OAuth2 flow: `get_auth_url()` → kullanıcı yetkilendirir → REST callback → token sakla
- `scan_folder()`: Klasörde `.docx`, `.txt`, Google Docs dosyalarını listeler, daha önce tarananları atlar
- `read_file()`: Google Doc → plain text export; .docx → tmp'ye indir → ZipArchive parse; .txt → direkt download
- `parse_docx()`: ZipArchive + DOMDocument ile `word/document.xml` okur, paragraf metinlerini döndürür
- Token otomatik yenileme (refresh_token)

---

### `includes/pipeline/class-content-pipeline.php`

_(305 satır — tam kaynak: `plugin/includes/pipeline/class-content-pipeline.php`)_

**`process($pipeline_id)`** adımları:
1. `duplicate_check` → Yinelenen tespiti
2. `claude_seo` → SEO/GEO optimizasyonu (API yoksa ham içerik)
3. `scheduling` → `Scheduler::find_next_slot()`
4. `create_post` → `wp_insert_post()` + Yoast meta + FAQ schema meta
5. `done` → `status=scheduled`

**`process_upload($file_path, $file_name, $source)`:**
- `.docx` → ZipArchive parse
- `.txt` → `file_get_contents`
- Başlık: ilk anlamlı satır veya dosya adından
- `wp_hyt_pipeline`'a ekler, pipeline_id döndürür

---

### `includes/admin/class-admin-menu.php` & `class-ajax.php`

_(145 + 466 satır — tam kaynak: `plugin/includes/admin/`)_

---

### `admin/views/dashboard.php`, `queue.php`, `logs.php`, `settings.php`

_(203 + 183 + 103 + 324 satır — tam kaynak: `plugin/admin/views/`)_

---

### `admin/css/style.css` & `admin/js/main.js`

_(588 + 524 satır — tam kaynak: `plugin/admin/`)_

**JS özellikleri:**
- Drag-drop + file input, duplicate önleme (name+size)
- Batch XHR upload (50 dosya/batch, progress bar)
- AJAX retry/cancel/bulk-retry
- Claude test butonu, settings save, API key show/hide toggle
- 30 sn'de bir kuyruk auto-refresh (processing varsa)

---

## Sonraki Adımlar (v2 için)

| Özellik | Durum |
|---------|-------|
| Canvas Design Engine (PIL/GD) — Featured image | Planlandı |
| HeyGen avatar video üretimi | Planlandı |
| Sosyal medya dağıtımı (Meta/YouTube/TikTok/LinkedIn) | Planlandı |
| İçerik genişletme (1000 kelime altını Claude ile büyüt) | Planlandı |
| İnsanlaştırma (AI detector bypass) | Planlandı |
| Çoklu Drive klasörü | Planlandı |
| E-posta bildirimleri | Planlandı |

---

*HYT Content Automation v1.0.0 · hyturkyilmaz.com · Mayıs 2026*
