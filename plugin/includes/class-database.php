<?php

declare(strict_types=1);

namespace HYT;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Database {

    public static function create_tables(): void {
        global $wpdb;

        $charset_collate = $wpdb->get_charset_collate();
        $db_version      = get_option( 'hyt_db_version', '0' );

        if ( version_compare( $db_version, '1.0.0', '>=' ) ) {
            return;
        }

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

    public static function get_pipeline_table(): string {
        global $wpdb;
        return $wpdb->prefix . 'hyt_pipeline';
    }

    public static function get_logs_table(): string {
        global $wpdb;
        return $wpdb->prefix . 'hyt_logs';
    }

    /**
     * Get pipeline stats counts.
     *
     * @return array<string,int>
     */
    public static function get_stats(): array {
        global $wpdb;
        $table = self::get_pipeline_table();

        $rows = $wpdb->get_results(
            "SELECT status, COUNT(*) as cnt FROM {$table} GROUP BY status",
            ARRAY_A
        );

        $stats = [
            'total'      => 0,
            'pending'    => 0,
            'processing' => 0,
            'duplicate'  => 0,
            'scheduled'  => 0,
            'published'  => 0,
            'failed'     => 0,
            'cancelled'  => 0,
        ];

        foreach ( $rows as $row ) {
            $stats[ $row['status'] ] = (int) $row['cnt'];
            $stats['total']         += (int) $row['cnt'];
        }

        return $stats;
    }

    /**
     * Insert a new pipeline item.
     *
     * @param array<string,mixed> $data
     * @return int|false Inserted ID or false on failure.
     */
    public static function insert_pipeline( array $data ): int|false {
        global $wpdb;

        $data['created_at'] = current_time( 'mysql' );
        $data['updated_at'] = current_time( 'mysql' );

        $result = $wpdb->insert( self::get_pipeline_table(), $data );

        if ( false === $result ) {
            return false;
        }

        return (int) $wpdb->insert_id;
    }

    /**
     * Update a pipeline item.
     *
     * @param int                 $id
     * @param array<string,mixed> $data
     */
    public static function update_pipeline( int $id, array $data ): void {
        global $wpdb;
        $data['updated_at'] = current_time( 'mysql' );
        $wpdb->update( self::get_pipeline_table(), $data, [ 'id' => $id ] );
    }

    /**
     * Get a single pipeline item.
     */
    public static function get_pipeline_item( int $id ): ?object {
        global $wpdb;
        $table = self::get_pipeline_table();
        return $wpdb->get_row( $wpdb->prepare( "SELECT * FROM {$table} WHERE id = %d", $id ) );
    }

    /**
     * Get paginated pipeline items.
     *
     * @param array<string,mixed> $args
     * @return array{items: array, total: int}
     */
    public static function get_pipeline_items( array $args = [] ): array {
        global $wpdb;
        $table = self::get_pipeline_table();

        $defaults = [
            'status'   => '',
            'per_page' => 30,
            'page'     => 1,
            'orderby'  => 'created_at',
            'order'    => 'DESC',
        ];

        $args    = wp_parse_args( $args, $defaults );
        $offset  = ( (int) $args['page'] - 1 ) * (int) $args['per_page'];
        $orderby = sanitize_sql_orderby( $args['orderby'] . ' ' . $args['order'] ) ?: 'created_at DESC';

        $where = '';
        $params = [];

        if ( ! empty( $args['status'] ) && 'all' !== $args['status'] ) {
            $where    = 'WHERE status = %s';
            $params[] = $args['status'];
        }

        $total = (int) $wpdb->get_var(
            $wpdb->prepare( "SELECT COUNT(*) FROM {$table} {$where}", ...$params )
        );

        $params[] = (int) $args['per_page'];
        $params[] = $offset;

        $items = $wpdb->get_results(
            $wpdb->prepare( "SELECT * FROM {$table} {$where} ORDER BY {$orderby} LIMIT %d OFFSET %d", ...$params )
        );

        return [
            'items' => $items ?: [],
            'total' => $total,
        ];
    }

    /**
     * Get recent pipeline items (for dashboard).
     *
     * @return array<object>
     */
    public static function get_recent_items( int $limit = 20 ): array {
        global $wpdb;
        $table = self::get_pipeline_table();
        return $wpdb->get_results(
            $wpdb->prepare( "SELECT * FROM {$table} ORDER BY created_at DESC LIMIT %d", $limit )
        ) ?: [];
    }
}
