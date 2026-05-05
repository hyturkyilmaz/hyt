<?php
declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

use HYT\Database;
use HYT\Api\Google_Drive;

$stats       = Database::get_stats();
$recent      = Database::get_recent_items( 20 );
$drive        = new Google_Drive();
$drive_connected = $drive->is_connected();
$last_scan   = get_option( 'hyt_gdrive_last_scan', '' );

/**
 * @param object $item
 * @return string
 */
function hyt_status_badge( object $item ): string {
    $labels = [
        'pending'    => [ 'label' => 'Bekliyor',   'class' => 'hyt-badge-pending' ],
        'processing' => [ 'label' => 'İşleniyor',  'class' => 'hyt-badge-processing' ],
        'duplicate'  => [ 'label' => 'Yinelenen',  'class' => 'hyt-badge-duplicate' ],
        'scheduled'  => [ 'label' => 'Planlandı',  'class' => 'hyt-badge-scheduled' ],
        'published'  => [ 'label' => 'Yayında',    'class' => 'hyt-badge-published' ],
        'failed'     => [ 'label' => 'Başarısız',  'class' => 'hyt-badge-failed' ],
        'cancelled'  => [ 'label' => 'İptal',      'class' => 'hyt-badge-cancelled' ],
    ];
    $info   = $labels[ $item->status ] ?? [ 'label' => $item->status, 'class' => 'hyt-badge-pending' ];
    return '<span class="hyt-badge ' . esc_attr( $info['class'] ) . '">' . esc_html( $info['label'] ) . '</span>';
}
?>
<div class="wrap hyt-ca-wrap">
    <h1 class="hyt-page-title">
        <span class="dashicons dashicons-admin-post"></span>
        HYT İçerik Otomasyonu – Dashboard
    </h1>

    <!-- Stats Row -->
    <div class="hyt-stats-row">
        <div class="hyt-stat-card">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['total'] ); ?></div>
            <div class="hyt-stat-label">Toplam</div>
        </div>
        <div class="hyt-stat-card hyt-stat-pending">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['pending'] + $stats['processing'] ); ?></div>
            <div class="hyt-stat-label">Bekliyor / İşleniyor</div>
        </div>
        <div class="hyt-stat-card hyt-stat-scheduled">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['scheduled'] ); ?></div>
            <div class="hyt-stat-label">Planlandı</div>
        </div>
        <div class="hyt-stat-card hyt-stat-failed">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['failed'] ); ?></div>
            <div class="hyt-stat-label">Başarısız</div>
        </div>
        <div class="hyt-stat-card hyt-stat-duplicate">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['duplicate'] ); ?></div>
            <div class="hyt-stat-label">Yinelenen</div>
        </div>
        <div class="hyt-stat-card hyt-stat-published">
            <div class="hyt-stat-number"><?php echo esc_html( $stats['published'] ); ?></div>
            <div class="hyt-stat-label">Yayında</div>
        </div>
    </div>

    <div class="hyt-two-col">
        <!-- Upload Section -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2><span class="dashicons dashicons-upload"></span> Dosya Yükle</h2>
            </div>
            <div class="hyt-card-body">
                <div id="hyt-drop-zone" class="hyt-drop-zone">
                    <div class="hyt-drop-icon">
                        <span class="dashicons dashicons-media-document"></span>
                    </div>
                    <p class="hyt-drop-text">Dosyaları buraya sürükleyin veya tıklayın</p>
                    <p class="hyt-drop-subtext">Desteklenen formatlar: .docx, .txt — Aynı anda 300 dosyaya kadar</p>
                    <input type="file" id="hyt-file-input" multiple accept=".docx,.txt" style="display:none;">
                    <div id="hyt-file-list" class="hyt-file-list"></div>
                </div>

                <div id="hyt-upload-progress" class="hyt-upload-progress" style="display:none;">
                    <div class="hyt-progress-bar-wrap">
                        <div id="hyt-progress-bar" class="hyt-progress-bar"></div>
                    </div>
                    <p id="hyt-progress-text">0 / 0 dosya yüklendi</p>
                </div>

                <div id="hyt-upload-result" class="hyt-upload-result" style="display:none;"></div>

                <div class="hyt-upload-actions">
                    <button id="hyt-upload-btn" class="button button-primary" disabled>
                        <span class="dashicons dashicons-upload"></span>
                        Yükle ve İşle
                    </button>
                    <span id="hyt-file-count" class="hyt-file-count"></span>
                </div>
            </div>
        </div>

        <!-- Google Drive Section -->
        <div class="hyt-card">
            <div class="hyt-card-header">
                <h2>
                    <span class="dashicons dashicons-cloud"></span>
                    Google Drive
                    <?php if ( $drive_connected ) : ?>
                        <span class="hyt-connection-badge connected">Bağlı</span>
                    <?php else : ?>
                        <span class="hyt-connection-badge disconnected">Bağlı Değil</span>
                    <?php endif; ?>
                </h2>
            </div>
            <div class="hyt-card-body">
                <?php if ( $drive_connected ) : ?>
                    <p class="hyt-drive-info">
                        <strong>Klasör ID:</strong>
                        <?php echo esc_html( get_option( 'hyt_gdrive_folder_id', '—' ) ); ?>
                    </p>
                    <?php if ( $last_scan ) : ?>
                        <p class="hyt-drive-info">
                            <strong>Son Tarama:</strong>
                            <?php echo esc_html( $last_scan ); ?>
                        </p>
                    <?php endif; ?>
                    <button id="hyt-gdrive-scan-btn" class="button button-primary">
                        <span class="dashicons dashicons-search"></span>
                        Drive Klasörünü Tara
                    </button>
                    <div id="hyt-gdrive-scan-result" class="hyt-notice" style="display:none;"></div>
                <?php else : ?>
                    <p>Google Drive entegrasyonu için lütfen <a href="<?php echo esc_url( admin_url( 'admin.php?page=hyt-ca-settings&tab=gdrive' ) ); ?>">Ayarlar</a> sayfasından bağlanın.</p>
                    <?php if ( $drive->is_configured() ) : ?>
                        <a href="<?php echo esc_url( $drive->get_auth_url() ); ?>" class="button button-secondary">
                            Google Drive'a Bağlan
                        </a>
                    <?php endif; ?>
                <?php endif; ?>
            </div>
        </div>
    </div>

    <!-- Recent Queue -->
    <div class="hyt-card hyt-full-width">
        <div class="hyt-card-header">
            <h2><span class="dashicons dashicons-list-view"></span> Son İşlemler</h2>
            <a href="<?php echo esc_url( admin_url( 'admin.php?page=hyt-ca-queue' ) ); ?>" class="button button-secondary">Tümünü Gör</a>
        </div>
        <div class="hyt-card-body hyt-no-padding">
            <?php if ( empty( $recent ) ) : ?>
                <p class="hyt-empty-state">Henüz işlem yok. Dosya yükleyerek başlayın.</p>
            <?php else : ?>
                <table class="widefat hyt-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Başlık</th>
                            <th>Kaynak</th>
                            <th>Durum</th>
                            <th>Adım</th>
                            <th>Planlanma</th>
                            <th>İşlemler</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php foreach ( $recent as $item ) : ?>
                            <tr>
                                <td><?php echo esc_html( $item->id ); ?></td>
                                <td>
                                    <strong><?php echo esc_html( $item->original_title ?: $item->file_name ); ?></strong>
                                    <br><small class="hyt-filename"><?php echo esc_html( $item->file_name ); ?></small>
                                </td>
                                <td>
                                    <?php echo $item->source === 'gdrive'
                                        ? '<span class="dashicons dashicons-cloud" title="Google Drive"></span>'
                                        : '<span class="dashicons dashicons-upload" title="Manuel"></span>'; ?>
                                </td>
                                <td><?php echo hyt_status_badge( $item ); ?></td>
                                <td><code><?php echo esc_html( $item->step ?: '—' ); ?></code></td>
                                <td><?php echo $item->scheduled_at ? esc_html( date_i18n( 'd.m.Y H:i', strtotime( $item->scheduled_at ) ) ) : '—'; ?></td>
                                <td class="hyt-actions">
                                    <?php if ( in_array( $item->status, [ 'failed', 'duplicate' ], true ) ) : ?>
                                        <button class="button button-small hyt-btn-retry" data-id="<?php echo esc_attr( $item->id ); ?>">Tekrar</button>
                                    <?php endif; ?>
                                    <?php if ( $item->post_id ) : ?>
                                        <a href="<?php echo esc_url( get_edit_post_link( (int) $item->post_id ) ); ?>" class="button button-small" target="_blank">Post</a>
                                    <?php endif; ?>
                                    <?php if ( in_array( $item->status, [ 'pending', 'scheduled' ], true ) ) : ?>
                                        <button class="button button-small hyt-btn-cancel" data-id="<?php echo esc_attr( $item->id ); ?>">İptal</button>
                                    <?php endif; ?>
                                </td>
                            </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            <?php endif; ?>
        </div>
    </div>
</div>
