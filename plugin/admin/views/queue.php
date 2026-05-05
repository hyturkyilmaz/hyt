<?php
declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

use HYT\Database;

$status_filter = sanitize_key( $_GET['status'] ?? 'all' );
$page          = max( 1, (int) ( $_GET['paged'] ?? 1 ) );
$per_page      = 30;

$data       = Database::get_pipeline_items( [
    'status'   => $status_filter,
    'page'     => $page,
    'per_page' => $per_page,
] );
$items      = $data['items'];
$total      = $data['total'];
$total_pages= (int) ceil( $total / $per_page );
$stats      = Database::get_stats();

$tabs = [
    'all'        => 'Tümü (' . $stats['total'] . ')',
    'pending'    => 'Bekliyor (' . $stats['pending'] . ')',
    'processing' => 'İşleniyor (' . $stats['processing'] . ')',
    'duplicate'  => 'Yinelenen (' . $stats['duplicate'] . ')',
    'scheduled'  => 'Planlandı (' . $stats['scheduled'] . ')',
    'published'  => 'Yayında (' . $stats['published'] . ')',
    'failed'     => 'Başarısız (' . $stats['failed'] . ')',
];

function hyt_queue_status_badge( string $status ): string {
    $map = [
        'pending'    => [ 'Bekliyor',   'hyt-badge-pending' ],
        'processing' => [ 'İşleniyor',  'hyt-badge-processing' ],
        'duplicate'  => [ 'Yinelenen',  'hyt-badge-duplicate' ],
        'scheduled'  => [ 'Planlandı',  'hyt-badge-scheduled' ],
        'published'  => [ 'Yayında',    'hyt-badge-published' ],
        'failed'     => [ 'Başarısız',  'hyt-badge-failed' ],
        'cancelled'  => [ 'İptal',      'hyt-badge-cancelled' ],
    ];
    $info = $map[ $status ] ?? [ $status, 'hyt-badge-pending' ];
    return '<span class="hyt-badge ' . esc_attr( $info[1] ) . '">' . esc_html( $info[0] ) . '</span>';
}
?>
<div class="wrap hyt-ca-wrap">
    <h1 class="hyt-page-title">
        <span class="dashicons dashicons-list-view"></span>
        İçerik Kuyruğu
    </h1>

    <!-- Filter Tabs -->
    <nav class="nav-tab-wrapper hyt-queue-tabs">
        <?php foreach ( $tabs as $key => $label ) :
            $url     = add_query_arg( [ 'page' => 'hyt-ca-queue', 'status' => $key ], admin_url( 'admin.php' ) );
            $active  = $status_filter === $key ? ' nav-tab-active' : '';
        ?>
            <a href="<?php echo esc_url( $url ); ?>" class="nav-tab<?php echo $active; ?>">
                <?php echo esc_html( $label ); ?>
            </a>
        <?php endforeach; ?>
    </nav>

    <!-- Bulk Actions -->
    <div class="hyt-bulk-actions">
        <?php if ( $stats['failed'] > 0 ) : ?>
            <button id="hyt-retry-all-failed" class="button">
                <span class="dashicons dashicons-update"></span>
                Tüm Başarısızları Tekrar Dene (<?php echo esc_html( $stats['failed'] ); ?>)
            </button>
        <?php endif; ?>
        <span id="hyt-bulk-result" class="hyt-inline-notice" style="display:none;"></span>
    </div>

    <!-- Queue Table -->
    <div id="hyt-queue-table-wrap">
        <?php if ( empty( $items ) ) : ?>
            <div class="hyt-empty-state">
                <span class="dashicons dashicons-smiley"></span>
                <p>Bu kategoride öğe yok.</p>
            </div>
        <?php else : ?>
            <table class="widefat hyt-table hyt-queue-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Dosya Adı</th>
                        <th>Başlık</th>
                        <th>Kaynak</th>
                        <th>Durum</th>
                        <th>Adım</th>
                        <th>Eşleşen Post</th>
                        <th>Planlanma</th>
                        <th>İşlemler</th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ( $items as $item ) :
                        $matched = '';
                        if ( $item->status === 'duplicate' && $item->error_message ) {
                            $matched = '<span title="' . esc_attr( $item->error_message ) . '" class="hyt-dup-info">ℹ</span>';
                        }
                    ?>
                        <tr class="hyt-queue-row" id="hyt-row-<?php echo esc_attr( $item->id ); ?>" data-status="<?php echo esc_attr( $item->status ); ?>">
                            <td><?php echo esc_html( $item->id ); ?></td>
                            <td class="hyt-td-filename">
                                <span title="<?php echo esc_attr( $item->file_name ?? '' ); ?>">
                                    <?php echo esc_html( mb_strimwidth( $item->file_name ?? '', 0, 40, '...' ) ); ?>
                                </span>
                            </td>
                            <td class="hyt-td-title">
                                <?php echo esc_html( mb_strimwidth( $item->original_title ?: '—', 0, 60, '...' ) ); ?>
                            </td>
                            <td>
                                <?php echo $item->source === 'gdrive'
                                    ? '<span class="dashicons dashicons-cloud" title="Google Drive"></span> Drive'
                                    : '<span class="dashicons dashicons-upload" title="Manuel"></span> Manuel'; ?>
                            </td>
                            <td><?php echo hyt_queue_status_badge( $item->status ); ?></td>
                            <td><code class="hyt-step"><?php echo esc_html( $item->step ?: '—' ); ?></code></td>
                            <td><?php echo $matched; ?></td>
                            <td>
                                <?php echo $item->scheduled_at
                                    ? esc_html( date_i18n( 'd.m.Y H:i', strtotime( $item->scheduled_at ) ) )
                                    : '—'; ?>
                            </td>
                            <td class="hyt-actions">
                                <?php if ( in_array( $item->status, [ 'failed', 'duplicate', 'cancelled' ], true ) ) : ?>
                                    <button class="button button-small hyt-btn-retry"
                                            data-id="<?php echo esc_attr( $item->id ); ?>"
                                            title="Tekrar İşle">
                                        <span class="dashicons dashicons-update"></span>
                                    </button>
                                <?php endif; ?>
                                <?php if ( $item->post_id ) :
                                    $edit_url = get_edit_post_link( (int) $item->post_id );
                                ?>
                                    <a href="<?php echo esc_url( $edit_url ); ?>"
                                       class="button button-small"
                                       target="_blank"
                                       title="WP Post'u Düzenle">
                                        <span class="dashicons dashicons-edit"></span>
                                    </a>
                                <?php endif; ?>
                                <?php if ( ! in_array( $item->status, [ 'cancelled', 'published' ], true ) ) : ?>
                                    <button class="button button-small hyt-btn-cancel"
                                            data-id="<?php echo esc_attr( $item->id ); ?>"
                                            title="İptal Et">
                                        <span class="dashicons dashicons-no"></span>
                                    </button>
                                <?php endif; ?>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>

            <!-- Pagination -->
            <?php if ( $total_pages > 1 ) : ?>
                <div class="tablenav bottom hyt-pagination">
                    <div class="tablenav-pages">
                        <span class="displaying-num">
                            <?php echo esc_html( sprintf( '%d öğe', $total ) ); ?>
                        </span>
                        <?php
                        $base_url = add_query_arg( [ 'page' => 'hyt-ca-queue', 'status' => $status_filter ], admin_url( 'admin.php' ) );
                        for ( $p = 1; $p <= $total_pages; $p++ ) :
                            $url    = add_query_arg( 'paged', $p, $base_url );
                            $active = $p === $page ? ' current' : '';
                        ?>
                            <a href="<?php echo esc_url( $url ); ?>"
                               class="button button-small<?php echo $active; ?>">
                                <?php echo esc_html( $p ); ?>
                            </a>
                        <?php endfor; ?>
                    </div>
                </div>
            <?php endif; ?>
        <?php endif; ?>
    </div>
</div>
