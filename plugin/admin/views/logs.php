<?php
declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

use HYT\Logger;

$level = sanitize_key( $_GET['level'] ?? '' );
$page  = max( 1, (int) ( $_GET['paged'] ?? 1 ) );

$data       = Logger::get_logs( [ 'level' => $level, 'page' => $page ] );
$items      = $data['items'];
$total      = $data['total'];
$total_pages= (int) ceil( $total / 50 );

$level_tabs = [
    ''        => 'Tümü',
    'info'    => 'Bilgi',
    'warning' => 'Uyarı',
    'error'   => 'Hata',
];
?>
<div class="wrap hyt-ca-wrap">
    <h1 class="hyt-page-title">
        <span class="dashicons dashicons-media-text"></span>
        Sistem Logları
    </h1>

    <nav class="nav-tab-wrapper">
        <?php foreach ( $level_tabs as $key => $label ) :
            $url    = add_query_arg( [ 'page' => 'hyt-ca-logs', 'level' => $key ], admin_url( 'admin.php' ) );
            $active = $level === $key ? ' nav-tab-active' : '';
        ?>
            <a href="<?php echo esc_url( $url ); ?>" class="nav-tab<?php echo $active; ?>">
                <?php echo esc_html( $label ); ?>
            </a>
        <?php endforeach; ?>
    </nav>

    <br>

    <?php if ( empty( $items ) ) : ?>
        <p class="hyt-empty-state">Log kaydı yok.</p>
    <?php else : ?>
        <table class="widefat hyt-table">
            <thead>
                <tr>
                    <th>Zaman</th>
                    <th>Seviye</th>
                    <th>Bağlam</th>
                    <th>Pipeline #</th>
                    <th>Mesaj</th>
                </tr>
            </thead>
            <tbody>
                <?php foreach ( $items as $log ) :
                    $level_class = match ( $log->level ) {
                        'error'   => 'hyt-log-error',
                        'warning' => 'hyt-log-warning',
                        default   => 'hyt-log-info',
                    };
                ?>
                    <tr class="<?php echo esc_attr( $level_class ); ?>">
                        <td class="hyt-td-time"><?php echo esc_html( $log->created_at ); ?></td>
                        <td>
                            <span class="hyt-badge <?php echo esc_attr( 'hyt-badge-' . $log->level ); ?>">
                                <?php echo esc_html( strtoupper( $log->level ) ); ?>
                            </span>
                        </td>
                        <td><code><?php echo esc_html( $log->context ); ?></code></td>
                        <td>
                            <?php if ( $log->pipeline_id ) : ?>
                                <a href="<?php echo esc_url( add_query_arg( [ 'page' => 'hyt-ca-queue' ], admin_url( 'admin.php' ) ) ); ?>">
                                    #<?php echo esc_html( $log->pipeline_id ); ?>
                                </a>
                            <?php else : ?>
                                —
                            <?php endif; ?>
                        </td>
                        <td><?php echo esc_html( $log->message ); ?></td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>

        <?php if ( $total_pages > 1 ) : ?>
            <div class="tablenav bottom hyt-pagination">
                <div class="tablenav-pages">
                    <?php for ( $p = 1; $p <= $total_pages; $p++ ) :
                        $url    = add_query_arg( [ 'page' => 'hyt-ca-logs', 'level' => $level, 'paged' => $p ], admin_url( 'admin.php' ) );
                        $active = $p === $page ? ' current' : '';
                    ?>
                        <a href="<?php echo esc_url( $url ); ?>" class="button button-small<?php echo $active; ?>">
                            <?php echo esc_html( $p ); ?>
                        </a>
                    <?php endfor; ?>
                </div>
            </div>
        <?php endif; ?>
    <?php endif; ?>
</div>
