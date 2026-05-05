<?php

declare(strict_types=1);

namespace HYT;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Scheduler {

    public static function register_cron(): void {
        // Add custom interval: every 5 minutes
        add_filter( 'cron_schedules', function ( array $schedules ): array {
            if ( ! isset( $schedules['hyt_five_minutes'] ) ) {
                $schedules['hyt_five_minutes'] = [
                    'interval' => 300,
                    'display'  => __( 'Her 5 dakika', 'hyt-content-automation' ),
                ];
            }
            return $schedules;
        } );

        if ( ! wp_next_scheduled( 'hyt_process_queue' ) ) {
            wp_schedule_event( time(), 'hyt_five_minutes', 'hyt_process_queue' );
        }
    }

    /**
     * Find the next available publishing slot.
     * Slot time: 08:45 (configurable via option hyt_schedule_time, default "08:45")
     * Skips dates already taken by WP future posts or pipeline items.
     * Respects allowed days of week from options (hyt_schedule_days).
     * Skips dates in holiday list (hyt_holiday_dates JSON array of "Y-m-d" strings).
     */
    public static function find_next_slot(): \DateTime {
        $slot_time     = get_option( 'hyt_schedule_time', '08:45' );
        $allowed_days  = get_option( 'hyt_schedule_days', [ '1','2','3','4','5','6','0' ] ); // 0=Sun..6=Sat
        $holiday_dates = [];

        $holidays_raw = get_option( 'hyt_holiday_dates', '' );
        if ( $holidays_raw ) {
            $decoded = json_decode( $holidays_raw, true );
            if ( is_array( $decoded ) ) {
                $holiday_dates = $decoded;
            }
        }

        $taken_dates = self::get_scheduled_dates();

        [$hour, $minute] = array_map( 'intval', explode( ':', $slot_time ) );

        $start = new \DateTime( 'now', wp_timezone() );
        $start->setTime( $hour, $minute, 0 );

        // If today's slot is in the past, start from tomorrow
        $now = new \DateTime( 'now', wp_timezone() );
        if ( $start <= $now ) {
            $start->modify( '+1 day' );
        }

        $max_days = 365;
        for ( $i = 0; $i < $max_days; $i++ ) {
            $day_of_week = $start->format( 'w' ); // 0=Sunday, 6=Saturday
            $date_str    = $start->format( 'Y-m-d' );

            // Check allowed day
            if ( ! in_array( (string) $day_of_week, (array) $allowed_days, true ) ) {
                $start->modify( '+1 day' );
                continue;
            }

            // Check holiday
            if ( in_array( $date_str, $holiday_dates, true ) ) {
                $start->modify( '+1 day' );
                continue;
            }

            // Check if slot is taken
            $slot_datetime = $date_str . ' ' . sprintf( '%02d:%02d:00', $hour, $minute );
            if ( ! in_array( $slot_datetime, $taken_dates, true ) ) {
                return $start;
            }

            $start->modify( '+1 day' );
        }

        // Fallback (should never happen in practice)
        return $start;
    }

    /**
     * Returns array of datetime strings ("Y-m-d H:i:s") already taken.
     *
     * @return array<string>
     */
    public static function get_scheduled_dates(): array {
        global $wpdb;

        $slot_time    = get_option( 'hyt_schedule_time', '08:45' );
        [$hour, $min] = array_map( 'intval', explode( ':', $slot_time ) );
        $time_suffix  = sprintf( ' %02d:%02d:00', $hour, $min );

        // WP future posts
        $wp_dates = $wpdb->get_col(
            "SELECT DATE_FORMAT(post_date, '%Y-%m-%d') FROM {$wpdb->posts}
             WHERE post_status = 'future'"
        );

        // Pipeline scheduled items
        $pipeline_table = Database::get_pipeline_table();
        $pipeline_dates = $wpdb->get_col(
            "SELECT DATE_FORMAT(scheduled_at, '%Y-%m-%d') FROM {$pipeline_table}
             WHERE scheduled_at IS NOT NULL AND status IN ('scheduled','processing','pending')"
        );

        $taken = [];
        foreach ( array_merge( (array) $wp_dates, (array) $pipeline_dates ) as $date ) {
            if ( $date ) {
                $taken[] = $date . $time_suffix;
            }
        }

        return array_unique( $taken );
    }

    /**
     * Process queue: run pipeline for pending items (up to 10 at a time).
     */
    public static function process_queue(): void {
        global $wpdb;

        $table = Database::get_pipeline_table();

        $items = $wpdb->get_results(
            $wpdb->prepare(
                "SELECT id FROM {$table} WHERE status = 'pending' ORDER BY created_at ASC LIMIT %d",
                10
            )
        );

        if ( empty( $items ) ) {
            return;
        }

        $pipeline = new Pipeline\Content_Pipeline();

        foreach ( $items as $item ) {
            try {
                $pipeline->process( (int) $item->id );
            } catch ( \Throwable $e ) {
                Logger::error(
                    'Pipeline işleminde beklenmeyen hata: ' . $e->getMessage(),
                    'scheduler',
                    [ 'trace' => $e->getTraceAsString() ],
                    (int) $item->id
                );
                Database::update_pipeline( (int) $item->id, [
                    'status'        => 'failed',
                    'error_message' => $e->getMessage(),
                ] );
            }
        }
    }
}
