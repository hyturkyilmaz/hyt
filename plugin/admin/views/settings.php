<?php
declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

use HYT\Api\Google_Drive;

$active_tab = sanitize_key( $_GET['tab'] ?? 'api' );
$drive = new Google_Drive();
$drive_connected = $drive->is_connected();

// Saved messages
$connected_msg  = isset( $_GET['connected'] ) ? '<div class="notice notice-success"><p>Google Drive başarıyla bağlandı.</p></div>' : '';
$error_msg      = isset( $_GET['error'] )     ? '<div class="notice notice-error"><p>Google Drive bağlantısı başarısız oldu.</p></div>' : '';

// Options
$claude_api_key    = (string) get_option( 'hyt_claude_api_key', '' );
$claude_model      = (string) get_option( 'hyt_claude_model', 'claude-sonnet-4-5' );
$gdrive_client_id  = (string) get_option( 'hyt_gdrive_client_id', '' );
$gdrive_client_sec = (string) get_option( 'hyt_gdrive_client_secret', '' );
$gdrive_folder_id  = (string) get_option( 'hyt_gdrive_folder_id', '' );
$gdrive_frequency  = (string) get_option( 'hyt_gdrive_frequency', '1hour' );
$schedule_time     = (string) get_option( 'hyt_schedule_time', '08:45' );
$schedule_days     = (array)  get_option( 'hyt_schedule_days', [ '0','1','2','3','4','5','6' ] );
$schedule_author   = (int)    get_option( 'hyt_schedule_author', 1 );
$schedule_category = (int)    get_option( 'hyt_schedule_category', 0 );
$holiday_dates_raw = (string) get_option( 'hyt_holiday_dates', '' );

$users      = get_users( [ 'role__in' => [ 'administrator', 'editor', 'author' ] ] );
$categories = get_categories( [ 'hide_empty' => false ] );

$tabs = [
    'api'      => 'API Anahtarları',
    'gdrive'   => 'Google Drive',
    'schedule' => 'Yayın Planı',
    'holidays' => 'Tatil Günleri',
];
?>
<div class="wrap hyt-ca-wrap">
    <h1 class="hyt-page-title">
        <span class="dashicons dashicons-admin-settings"></span>
        Ayarlar
    </h1>

    <?php echo $connected_msg; ?>
    <?php echo $error_msg; ?>

    <div id="hyt-settings-notice" class="hyt-inline-notice" style="display:none;"></div>

    <nav class="nav-tab-wrapper">
        <?php foreach ( $tabs as $key => $label ) :
            $url    = add_query_arg( [ 'page' => 'hyt-ca-settings', 'tab' => $key ], admin_url( 'admin.php' ) );
            $active = $active_tab === $key ? ' nav-tab-active' : '';
        ?>
            <a href="<?php echo esc_url( $url ); ?>" class="nav-tab<?php echo $active; ?>">
                <?php echo esc_html( $label ); ?>
            </a>
        <?php endforeach; ?>
    </nav>

    <div class="hyt-settings-body">

        <?php if ( $active_tab === 'api' ) : ?>
        <!-- API Keys Tab -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2>Claude API</h2>
            </div>
            <div class="hyt-card-body">
                <table class="form-table">
                    <tr>
                        <th scope="row"><label for="claude_api_key">API Anahtarı</label></th>
                        <td>
                            <div class="hyt-input-group">
                                <input type="password" id="claude_api_key" name="claude_api_key"
                                       value="<?php echo esc_attr( $claude_api_key ); ?>"
                                       class="regular-text" autocomplete="new-password">
                                <button type="button" id="hyt-toggle-api-key" class="button">
                                    <span class="dashicons dashicons-visibility"></span>
                                </button>
                            </div>
                            <p class="description">
                                <a href="https://console.anthropic.com/account/keys" target="_blank">Anthropic Console</a>'dan API anahtarınızı alın.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="claude_model">Model</label></th>
                        <td>
                            <select id="claude_model" name="claude_model">
                                <option value="claude-opus-4-5" <?php selected( $claude_model, 'claude-opus-4-5' ); ?>>Claude Opus 4.5 (En Güçlü)</option>
                                <option value="claude-sonnet-4-5" <?php selected( $claude_model, 'claude-sonnet-4-5' ); ?>>Claude Sonnet 4.5 (Dengeli)</option>
                                <option value="claude-haiku-4-5" <?php selected( $claude_model, 'claude-haiku-4-5' ); ?>>Claude Haiku 4.5 (Hızlı)</option>
                            </select>
                        </td>
                    </tr>
                </table>
                <div class="hyt-settings-actions">
                    <button id="hyt-save-api-settings" class="button button-primary" data-tab="api">
                        Kaydet
                    </button>
                    <button id="hyt-test-claude-btn" class="button">
                        <span class="dashicons dashicons-controls-play"></span>
                        Bağlantıyı Test Et
                    </button>
                    <span id="hyt-test-claude-result" class="hyt-inline-notice" style="display:none;"></span>
                </div>
            </div>
        </div>

        <?php elseif ( $active_tab === 'gdrive' ) : ?>
        <!-- Google Drive Tab -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2>
                    Google Drive OAuth2
                    <?php if ( $drive_connected ) : ?>
                        <span class="hyt-connection-badge connected">Bağlı</span>
                    <?php else : ?>
                        <span class="hyt-connection-badge disconnected">Bağlı Değil</span>
                    <?php endif; ?>
                </h2>
            </div>
            <div class="hyt-card-body">
                <p class="description" style="margin-bottom:16px;">
                    Google Cloud Console'da bir OAuth 2.0 Client ID oluşturun. Redirect URI olarak şunu ekleyin:<br>
                    <code><?php echo esc_html( rest_url( 'hyt/v1/gdrive-callback' ) ); ?></code>
                </p>
                <table class="form-table">
                    <tr>
                        <th scope="row"><label for="gdrive_client_id">Client ID</label></th>
                        <td>
                            <input type="text" id="gdrive_client_id" name="gdrive_client_id"
                                   value="<?php echo esc_attr( $gdrive_client_id ); ?>"
                                   class="regular-text">
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="gdrive_client_secret">Client Secret</label></th>
                        <td>
                            <input type="password" id="gdrive_client_secret" name="gdrive_client_secret"
                                   value="<?php echo esc_attr( $gdrive_client_sec ); ?>"
                                   class="regular-text" autocomplete="new-password">
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="gdrive_folder_id">Klasör ID</label></th>
                        <td>
                            <input type="text" id="gdrive_folder_id" name="gdrive_folder_id"
                                   value="<?php echo esc_attr( $gdrive_folder_id ); ?>"
                                   class="regular-text">
                            <p class="description">Drive klasörünüzün URL'sindeki ID: drive.google.com/drive/folders/<strong>BURASI</strong></p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="gdrive_frequency">Tarama Sıklığı</label></th>
                        <td>
                            <select id="gdrive_frequency" name="gdrive_frequency">
                                <option value="15min"  <?php selected( $gdrive_frequency, '15min' ); ?>>Her 15 dakika</option>
                                <option value="1hour"  <?php selected( $gdrive_frequency, '1hour' ); ?>>Her 1 saat</option>
                                <option value="6hour"  <?php selected( $gdrive_frequency, '6hour' ); ?>>Her 6 saat</option>
                                <option value="daily"  <?php selected( $gdrive_frequency, 'daily' ); ?>>Günde 1 kez</option>
                            </select>
                        </td>
                    </tr>
                </table>

                <div class="hyt-settings-actions">
                    <button id="hyt-save-gdrive-settings" class="button button-primary" data-tab="gdrive">
                        Kaydet
                    </button>
                    <?php if ( $drive_connected ) : ?>
                        <button id="hyt-gdrive-disconnect-btn" class="button">
                            <span class="dashicons dashicons-no-alt"></span>
                            Bağlantıyı Kes
                        </button>
                    <?php else : ?>
                        <button id="hyt-gdrive-connect-btn" class="button button-secondary">
                            <span class="dashicons dashicons-cloud"></span>
                            Google Drive'a Bağlan
                        </button>
                    <?php endif; ?>
                    <span id="hyt-gdrive-result" class="hyt-inline-notice" style="display:none;"></span>
                </div>
            </div>
        </div>

        <?php elseif ( $active_tab === 'schedule' ) : ?>
        <!-- Schedule Tab -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2>Yayın Planı</h2>
            </div>
            <div class="hyt-card-body">
                <table class="form-table">
                    <tr>
                        <th scope="row">Günler</th>
                        <td>
                            <fieldset>
                                <?php
                                $day_names = [
                                    '1' => 'Pazartesi',
                                    '2' => 'Salı',
                                    '3' => 'Çarşamba',
                                    '4' => 'Perşembe',
                                    '5' => 'Cuma',
                                    '6' => 'Cumartesi',
                                    '0' => 'Pazar',
                                ];
                                foreach ( $day_names as $val => $name ) :
                                    $checked = in_array( (string) $val, $schedule_days, true ) ? ' checked' : '';
                                ?>
                                    <label style="margin-right:16px; display:inline-block;">
                                        <input type="checkbox" name="schedule_days[]"
                                               value="<?php echo esc_attr( $val ); ?>"
                                               class="hyt-day-checkbox"<?php echo $checked; ?>>
                                        <?php echo esc_html( $name ); ?>
                                    </label>
                                <?php endforeach; ?>
                            </fieldset>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="schedule_time">Yayın Saati</label></th>
                        <td>
                            <input type="time" id="schedule_time" name="schedule_time"
                                   value="<?php echo esc_attr( $schedule_time ); ?>"
                                   class="small-text">
                            <p class="description">Varsayılan: 08:45</p>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="schedule_author">Yazar</label></th>
                        <td>
                            <select id="schedule_author" name="schedule_author">
                                <?php foreach ( $users as $user ) : ?>
                                    <option value="<?php echo esc_attr( $user->ID ); ?>"
                                            <?php selected( $schedule_author, $user->ID ); ?>>
                                        <?php echo esc_html( $user->display_name . ' (' . $user->user_login . ')' ); ?>
                                    </option>
                                <?php endforeach; ?>
                            </select>
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="schedule_category">Kategori</label></th>
                        <td>
                            <select id="schedule_category" name="schedule_category">
                                <option value="0">— Seçiniz —</option>
                                <?php foreach ( $categories as $cat ) : ?>
                                    <option value="<?php echo esc_attr( $cat->term_id ); ?>"
                                            <?php selected( $schedule_category, $cat->term_id ); ?>>
                                        <?php echo esc_html( $cat->name ); ?>
                                    </option>
                                <?php endforeach; ?>
                            </select>
                        </td>
                    </tr>
                </table>
                <div class="hyt-settings-actions">
                    <button id="hyt-save-schedule-settings" class="button button-primary" data-tab="schedule">
                        Kaydet
                    </button>
                </div>
            </div>
        </div>

        <?php elseif ( $active_tab === 'holidays' ) : ?>
        <!-- Holidays Tab -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2>Tatil Günleri</h2>
            </div>
            <div class="hyt-card-body">
                <p>Planlama dışında tutulacak tarihleri JSON dizisi olarak girin: <code>["2026-01-01", "2026-04-23"]</code></p>
                <textarea id="holiday_dates" name="holiday_dates" rows="8" class="large-text code"><?php echo esc_textarea( $holiday_dates_raw ?: '[]' ); ?></textarea>

                <div class="hyt-settings-actions">
                    <button id="hyt-save-holidays-settings" class="button button-primary" data-tab="holidays">
                        Kaydet
                    </button>
                </div>

                <hr>

                <h3>2026 Türkiye Resmi Tatilleri (Referans)</h3>
                <table class="widefat hyt-table" style="max-width:500px;">
                    <thead><tr><th>Tarih</th><th>Tatil</th></tr></thead>
                    <tbody>
                        <?php
                        $tr_holidays_2026 = [
                            '2026-01-01' => 'Yılbaşı',
                            '2026-03-20' => 'Ramazan Bayramı Arefe',
                            '2026-03-21' => 'Ramazan Bayramı 1. Gün',
                            '2026-03-22' => 'Ramazan Bayramı 2. Gün',
                            '2026-03-23' => 'Ramazan Bayramı 3. Gün',
                            '2026-04-23' => 'Ulusal Egemenlik ve Çocuk Bayramı',
                            '2026-05-01' => 'Emek ve Dayanışma Günü',
                            '2026-05-19' => 'Atatürk\'ü Anma, Gençlik ve Spor Bayramı',
                            '2026-05-27' => 'Kurban Bayramı Arefe',
                            '2026-05-28' => 'Kurban Bayramı 1. Gün',
                            '2026-05-29' => 'Kurban Bayramı 2. Gün',
                            '2026-05-30' => 'Kurban Bayramı 3. Gün',
                            '2026-05-31' => 'Kurban Bayramı 4. Gün',
                            '2026-07-15' => 'Demokrasi ve Millî Birlik Günü',
                            '2026-08-30' => 'Zafer Bayramı',
                            '2026-10-29' => 'Cumhuriyet Bayramı',
                        ];
                        foreach ( $tr_holidays_2026 as $date => $name ) : ?>
                            <tr>
                                <td><?php echo esc_html( date_i18n( 'd.m.Y', strtotime( $date ) ) ); ?></td>
                                <td><?php echo esc_html( $name ); ?></td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        </div>
        <?php endif; ?>

    </div><!-- .hyt-settings-body -->
</div>
