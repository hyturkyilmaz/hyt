<?php

declare(strict_types=1);

namespace HYT;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Logger {

    public static function info( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void {
        self::log( 'info', $message, $context, $data, $pipeline_id );
    }

    public static function warning( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void {
        self::log( 'warning', $message, $context, $data, $pipeline_id );
    }

    public static function error( string $message, string $context = '', mixed $data = null, ?int $pipeline_id = null ): void {
        self::log( 'error', $message, $context, $data, $pipeline_id );
    }

    private static function log( string $level, string $message, string $context, mixed $data, ?int $pipeline_id ): void {
        global $wpdb;

        $wpdb->insert(
            Database::get_logs_table(),
            [
                'pipeline_id' => $pipeline_id,
                'level'       => $level,
                'context'     => substr( $context, 0, 100 ),
                'message'     => $message,
                'data'        => $data !== null ? wp_json_encode( $data ) : null,
                'created_at'  => current_time( 'mysql' ),
            ]
        );
    }

    /**
     * Get logs with optional filters.
     *
     * @param array<string,mixed> $args
     * @return array{items: array, total: int}
     */
    public static function get_logs( array $args = [] ): array {
        global $wpdb;
        $table = Database::get_logs_table();

        $defaults = [
            'level'       => '',
            'pipeline_id' => null,
            'per_page'    => 50,
            'page'        => 1,
        ];

        $args   = wp_parse_args( $args, $defaults );
        $offset = ( (int) $args['page'] - 1 ) * (int) $args['per_page'];

        $wheres = [];
        $params = [];

        if ( ! empty( $args['level'] ) ) {
            $wheres[] = 'level = %s';
            $params[] = $args['level'];
        }

        if ( ! empty( $args['pipeline_id'] ) ) {
            $wheres[] = 'pipeline_id = %d';
            $params[] = (int) $args['pipeline_id'];
        }

        $where = $wheres ? 'WHERE ' . implode( ' AND ', $wheres ) : '';

        $count_params = $params;
        $total        = (int) $wpdb->get_var(
            $wpdb->prepare( "SELECT COUNT(*) FROM {$table} {$where}", ...$count_params )
        );

        $params[] = (int) $args['per_page'];
        $params[] = $offset;

        $items = $wpdb->get_results(
            $wpdb->prepare( "SELECT * FROM {$table} {$where} ORDER BY created_at DESC LIMIT %d OFFSET %d", ...$params )
        ) ?: [];

        return [ 'items' => $items, 'total' => $total ];
    }
}
