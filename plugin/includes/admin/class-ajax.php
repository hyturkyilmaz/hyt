<?php

declare(strict_types=1);

namespace HYT\Admin;

use HYT\Database;
use HYT\Logger;
use HYT\Scheduler;
use HYT\Api\Claude;
use HYT\Api\Google_Drive;
use HYT\Pipeline\Content_Pipeline;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Ajax {

    public function init(): void {
        $actions = [
            'hyt_upload_files',
            'hyt_process_item',
            'hyt_retry_item',
            'hyt_cancel_item',
            'hyt_get_queue',
            'hyt_get_stats',
            'hyt_test_claude',
            'hyt_save_settings',
            'hyt_gdrive_scan',
            'hyt_gdrive_connect',
            'hyt_gdrive_disconnect',
            'hyt_retry_all_failed',
            'hyt_get_logs',
        ];

        foreach ( $actions as $action ) {
            add_action( "wp_ajax_{$action}", [ $this, 'dispatch' ] );
        }
    }

    public function dispatch(): void {
        $action = sanitize_key( $_POST['action'] ?? $_GET['action'] ?? '' );
        $method = str_replace( 'hyt_', '', $action );
        $method = str_replace( '_', '_', $method ); // keep underscores

        $this->verify_nonce();
        $this->verify_capability();

        $handler = 'handle_' . $method;
        if ( method_exists( $this, $handler ) ) {
            $this->$handler();
        } else {
            wp_send_json_error( [ 'message' => 'Bilinmeyen işlem.' ] );
        }
    }

    /* -----------------------------------------------------------------------
     * Handlers
     * --------------------------------------------------------------------- */

    private function handle_upload_files(): void {
        if ( empty( $_FILES['files'] ) ) {
            wp_send_json_error( [ 'message' => 'Dosya seçilmedi.' ] );
        }

        $files    = $_FILES['files'];
        $pipeline = new Content_Pipeline();
        $results  = [];
        $errors   = [];

        // Normalize single vs multiple file uploads
        $count = is_array( $files['name'] ) ? count( $files['name'] ) : 1;

        for ( $i = 0; $i < $count; $i++ ) {
            $name     = is_array( $files['name'] )     ? $files['name'][$i]     : $files['name'];
            $tmp_name = is_array( $files['tmp_name'] ) ? $files['tmp_name'][$i] : $files['tmp_name'];
            $error    = is_array( $files['error'] )    ? $files['error'][$i]    : $files['error'];

            if ( $error !== UPLOAD_ERR_OK ) {
                $errors[] = "{$name}: Yükleme hatası kodu {$error}";
                continue;
            }

            $ext = strtolower( pathinfo( $name, PATHINFO_EXTENSION ) );
            if ( ! in_array( $ext, [ 'docx', 'txt' ], true ) ) {
                $errors[] = "{$name}: Desteklenmeyen dosya türü.";
                continue;
            }

            // Move to uploads/hyt-tmp/
            $uploads  = wp_upload_dir();
            $tmp_dir  = $uploads['basedir'] . '/hyt-tmp/';
            wp_mkdir_p( $tmp_dir );
            $dest = $tmp_dir . sanitize_file_name( $name );

            if ( ! move_uploaded_file( $tmp_name, $dest ) ) {
                $errors[] = "{$name}: Dosya taşınamadı.";
                continue;
            }

            try {
                $pipeline_id = $pipeline->process_upload( $dest, $name, 'manual' );
                $results[]   = [ 'file' => $name, 'pipeline_id' => $pipeline_id ];

                // Trigger processing immediately (async-like via shutdown)
                add_action( 'shutdown', function () use ( $pipeline_id, $pipeline ) {
                    $pipeline->process( $pipeline_id );
                } );
            } catch ( \Throwable $e ) {
                $errors[] = "{$name}: " . $e->getMessage();
                Logger::error( "Yükleme hatası: {$name} - " . $e->getMessage(), 'upload' );
            } finally {
                @unlink( $dest );
            }
        }

        wp_send_json_success( [
            'processed' => count( $results ),
            'errors'    => $errors,
            'items'     => $results,
        ] );
    }

    private function handle_process_item(): void {
        $id = (int) ( $_POST['id'] ?? 0 );
        if ( ! $id ) {
            wp_send_json_error( [ 'message' => 'Geçersiz ID.' ] );
        }

        $pipeline = new Content_Pipeline();
        $item     = Database::get_pipeline_item( $id );

        if ( ! $item ) {
            wp_send_json_error( [ 'message' => 'Öğe bulunamadı.' ] );
        }

        // Force status back to pending so pipeline will pick it up
        Database::update_pipeline( $id, [ 'status' => 'pending', 'step' => '', 'error_message' => null ] );
        $pipeline->process( $id );

        wp_send_json_success( [ 'message' => 'İşlem başlatıldı.' ] );
    }

    private function handle_retry_item(): void {
        $this->handle_process_item();
    }

    private function handle_cancel_item(): void {
        $id = (int) ( $_POST['id'] ?? 0 );
        if ( ! $id ) {
            wp_send_json_error( [ 'message' => 'Geçersiz ID.' ] );
        }

        $item = Database::get_pipeline_item( $id );
        if ( ! $item ) {
            wp_send_json_error( [ 'message' => 'Öğe bulunamadı.' ] );
        }

        // If there's a scheduled WP post, trash it
        if ( $item->post_id ) {
            wp_trash_post( (int) $item->post_id );
        }

        Database::update_pipeline( $id, [ 'status' => 'cancelled', 'step' => 'cancelled' ] );
        wp_send_json_success( [ 'message' => 'İptal edildi.' ] );
    }

    private function handle_get_queue(): void {
        $status   = sanitize_key( $_POST['status'] ?? 'all' );
        $page     = max( 1, (int) ( $_POST['page'] ?? 1 ) );
        $per_page = 30;

        $data  = Database::get_pipeline_items( [ 'status' => $status, 'page' => $page, 'per_page' => $per_page ] );
        $items = array_map( [ $this, 'format_pipeline_item' ], $data['items'] );

        wp_send_json_success( [
            'items'      => $items,
            'total'      => $data['total'],
            'page'       => $page,
            'total_pages'=> (int) ceil( $data['total'] / $per_page ),
        ] );
    }

    private function handle_get_stats(): void {
        wp_send_json_success( Database::get_stats() );
    }

    private function handle_test_claude(): void {
        $claude = new Claude();
        $result = $claude->test_connection();
        if ( $result['success'] ) {
            wp_send_json_success( $result );
        } else {
            wp_send_json_error( $result );
        }
    }

    private function handle_save_settings(): void {
        $tab = sanitize_key( $_POST['tab'] ?? 'api' );

        switch ( $tab ) {
            case 'api':
                $this->save_api_settings();
                break;
            case 'gdrive':
                $this->save_gdrive_settings();
                break;
            case 'schedule':
                $this->save_schedule_settings();
                break;
            case 'holidays':
                $this->save_holidays_settings();
                break;
            default:
                wp_send_json_error( [ 'message' => 'Bilinmeyen sekme.' ] );
        }

        wp_send_json_success( [ 'message' => 'Ayarlar kaydedildi.' ] );
    }

    private function save_api_settings(): void {
        if ( isset( $_POST['claude_api_key'] ) ) {
            $key = sanitize_text_field( $_POST['claude_api_key'] );
            if ( $key ) {
                update_option( 'hyt_claude_api_key', $key );
            }
        }
        if ( isset( $_POST['claude_model'] ) ) {
            $allowed_models = [ 'claude-opus-4-5', 'claude-sonnet-4-5', 'claude-haiku-4-5' ];
            $model = sanitize_text_field( $_POST['claude_model'] );
            if ( in_array( $model, $allowed_models, true ) ) {
                update_option( 'hyt_claude_model', $model );
            }
        }
    }

    private function save_gdrive_settings(): void {
        $fields = [ 'hyt_gdrive_client_id', 'hyt_gdrive_client_secret', 'hyt_gdrive_folder_id' ];
        foreach ( $fields as $field ) {
            $post_key = str_replace( 'hyt_gdrive_', 'gdrive_', $field );
            if ( isset( $_POST[ $post_key ] ) ) {
                update_option( $field, sanitize_text_field( $_POST[ $post_key ] ) );
            }
        }

        $allowed_frequencies = [ '15min', '1hour', '6hour', 'daily' ];
        if ( isset( $_POST['gdrive_frequency'] ) ) {
            $freq = sanitize_key( $_POST['gdrive_frequency'] );
            if ( in_array( $freq, $allowed_frequencies, true ) ) {
                update_option( 'hyt_gdrive_frequency', $freq );
            }
        }
    }

    private function save_schedule_settings(): void {
        if ( isset( $_POST['schedule_time'] ) ) {
            $time = sanitize_text_field( $_POST['schedule_time'] );
            if ( preg_match( '/^\d{2}:\d{2}$/', $time ) ) {
                update_option( 'hyt_schedule_time', $time );
            }
        }

        if ( isset( $_POST['schedule_days'] ) && is_array( $_POST['schedule_days'] ) ) {
            $days = array_map( 'sanitize_key', $_POST['schedule_days'] );
            update_option( 'hyt_schedule_days', $days );
        }

        if ( isset( $_POST['schedule_author'] ) ) {
            update_option( 'hyt_schedule_author', (int) $_POST['schedule_author'] );
        }

        if ( isset( $_POST['schedule_category'] ) ) {
            update_option( 'hyt_schedule_category', (int) $_POST['schedule_category'] );
        }
    }

    private function save_holidays_settings(): void {
        if ( isset( $_POST['holiday_dates'] ) ) {
            $raw = wp_unslash( $_POST['holiday_dates'] );
            // Validate JSON
            $decoded = json_decode( $raw, true );
            if ( is_array( $decoded ) ) {
                update_option( 'hyt_holiday_dates', wp_json_encode( $decoded ) );
            }
        }
    }

    private function handle_gdrive_scan(): void {
        $drive    = new Google_Drive();
        $pipeline = new Content_Pipeline();

        if ( ! $drive->is_connected() ) {
            wp_send_json_error( [ 'message' => 'Google Drive bağlı değil.' ] );
        }

        $files   = $drive->scan_folder();
        $added   = 0;
        $errors  = [];

        foreach ( $files as $file ) {
            try {
                $content = $drive->read_file( $file['id'], $file['mimeType'] );
                if ( ! $content ) {
                    $errors[] = "{$file['name']}: İçerik okunamadı.";
                    continue;
                }

                // Write to tmp file for pipeline
                $uploads  = wp_upload_dir();
                $tmp_dir  = $uploads['basedir'] . '/hyt-tmp/';
                wp_mkdir_p( $tmp_dir );
                $ext      = ( $file['mimeType'] === 'text/plain' ) ? 'txt' : 'txt';
                $tmp_path = $tmp_dir . sanitize_file_name( $file['name'] ) . '.' . $ext;
                file_put_contents( $tmp_path, $content );

                $pipeline_id = $pipeline->process_upload( $tmp_path, $file['name'] . '.txt', 'gdrive' );
                $drive->mark_scanned( $file['id'] );
                @unlink( $tmp_path );
                $added++;

                add_action( 'shutdown', function () use ( $pipeline_id, $pipeline ) {
                    $pipeline->process( $pipeline_id );
                } );
            } catch ( \Throwable $e ) {
                $errors[] = "{$file['name']}: " . $e->getMessage();
            }
        }

        update_option( 'hyt_gdrive_last_scan', current_time( 'mysql' ) );

        wp_send_json_success( [
            'added'  => $added,
            'errors' => $errors,
            'total'  => count( $files ),
        ] );
    }

    private function handle_gdrive_connect(): void {
        $drive = new Google_Drive();
        if ( ! $drive->is_configured() ) {
            wp_send_json_error( [ 'message' => 'Client ID ve Client Secret girilmemiş.' ] );
        }
        $auth_url = $drive->get_auth_url();
        wp_send_json_success( [ 'auth_url' => $auth_url ] );
    }

    private function handle_gdrive_disconnect(): void {
        $drive = new Google_Drive();
        $drive->disconnect();
        wp_send_json_success( [ 'message' => 'Google Drive bağlantısı kesildi.' ] );
    }

    private function handle_retry_all_failed(): void {
        global $wpdb;
        $table = Database::get_pipeline_table();

        $ids = $wpdb->get_col(
            "SELECT id FROM {$table} WHERE status = 'failed'"
        );

        if ( empty( $ids ) ) {
            wp_send_json_success( [ 'message' => 'Başarısız öğe yok.', 'count' => 0 ] );
        }

        $count    = 0;
        $pipeline = new Content_Pipeline();
        foreach ( $ids as $id ) {
            Database::update_pipeline( (int) $id, [
                'status'        => 'pending',
                'step'          => '',
                'error_message' => null,
            ] );
            $count++;
        }

        // Trigger queue processing on shutdown
        add_action( 'shutdown', function () {
            Scheduler::process_queue();
        } );

        wp_send_json_success( [ 'message' => "{$count} öğe yeniden kuyruğa alındı.", 'count' => $count ] );
    }

    private function handle_get_logs(): void {
        $level       = sanitize_key( $_POST['level'] ?? '' );
        $pipeline_id = (int) ( $_POST['pipeline_id'] ?? 0 );
        $page        = max( 1, (int) ( $_POST['page'] ?? 1 ) );

        $args = [ 'page' => $page, 'per_page' => 50 ];
        if ( $level ) {
            $args['level'] = $level;
        }
        if ( $pipeline_id ) {
            $args['pipeline_id'] = $pipeline_id;
        }

        $data  = Logger::get_logs( $args );
        $items = array_map( function ( $log ) {
            return [
                'id'          => $log->id,
                'pipeline_id' => $log->pipeline_id,
                'level'       => $log->level,
                'context'     => $log->context,
                'message'     => $log->message,
                'created_at'  => $log->created_at,
            ];
        }, $data['items'] );

        wp_send_json_success( [
            'items' => $items,
            'total' => $data['total'],
            'page'  => $page,
        ] );
    }

    /* -----------------------------------------------------------------------
     * Helpers
     * --------------------------------------------------------------------- */

    private function verify_nonce(): void {
        $nonce = sanitize_text_field( $_POST['nonce'] ?? $_GET['nonce'] ?? '' );
        if ( ! wp_verify_nonce( $nonce, 'hyt_ajax_nonce' ) ) {
            wp_send_json_error( [ 'message' => 'Güvenlik doğrulaması başarısız.' ], 403 );
        }
    }

    private function verify_capability(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( [ 'message' => 'Yetkiniz yok.' ], 403 );
        }
    }

    /**
     * Format a pipeline DB row for JSON output.
     *
     * @param object $item
     * @return array<string,mixed>
     */
    private function format_pipeline_item( object $item ): array {
        $post_url = '';
        if ( $item->post_id ) {
            $post_url = get_edit_post_link( (int) $item->post_id ) ?: '';
        }

        $matched_post_title = '';
        if ( $item->status === 'duplicate' && $item->error_message ) {
            $matched_post_title = $item->error_message;
        }

        return [
            'id'             => $item->id,
            'file_name'      => $item->file_name,
            'original_title' => $item->original_title,
            'source'         => $item->source,
            'status'         => $item->status,
            'step'           => $item->step,
            'word_count'     => $item->word_count,
            'scheduled_at'   => $item->scheduled_at,
            'post_id'        => $item->post_id,
            'post_url'       => $post_url,
            'error_message'  => $item->error_message,
            'created_at'     => $item->created_at,
        ];
    }
}
