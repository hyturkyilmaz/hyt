<?php

declare(strict_types=1);

namespace HYT\Pipeline;

use HYT\Database;
use HYT\Logger;
use HYT\Duplicate_Checker;
use HYT\Scheduler;
use HYT\Api\Claude;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Content_Pipeline {

    /**
     * Process a pipeline item by ID.
     * Steps: duplicate_check → claude_seo → scheduling → create_post
     */
    public function process( int $pipeline_id ): void {
        $item = Database::get_pipeline_item( $pipeline_id );

        if ( ! $item ) {
            Logger::error( "Pipeline item bulunamadı: #{$pipeline_id}", 'pipeline', null, $pipeline_id );
            return;
        }

        if ( ! in_array( $item->status, [ 'pending', 'failed' ], true ) ) {
            return; // already being processed or done
        }

        Database::update_pipeline( $pipeline_id, [
            'status' => 'processing',
            'step'   => 'duplicate_check',
        ] );

        Logger::info( "Pipeline başlatıldı: {$item->file_name}", 'pipeline', null, $pipeline_id );

        try {
            $title   = $item->original_title ?: $item->file_name;
            $content = $item->raw_content ?: '';

            /* ---- Step 1: Duplicate check ---- */
            $checker = new Duplicate_Checker();
            $dup     = $checker->check( $title, $content );

            if ( $dup['is_duplicate'] ) {
                $matched_id = $dup['matched_post']?->ID ?? null;
                Database::update_pipeline( $pipeline_id, [
                    'status'        => 'duplicate',
                    'step'          => 'duplicate_detected',
                    'error_message' => sprintf(
                        'Yinelenen içerik: %s (benzerlik: %%%d, eşleşen post ID: %d)',
                        $dup['match_type'],
                        $dup['similarity'],
                        $matched_id ?? 0
                    ),
                ] );
                Logger::warning(
                    "Yinelenen içerik tespit edildi: {$item->file_name}",
                    'pipeline',
                    $dup,
                    $pipeline_id
                );
                return;
            }

            /* ---- Step 2: Claude SEO optimization ---- */
            Database::update_pipeline( $pipeline_id, [ 'step' => 'claude_seo' ] );

            $seo_data          = null;
            $final_title       = $title;
            $final_content     = $content;
            $final_slug        = '';

            $claude = new Claude();
            if ( $claude->is_configured() ) {
                $seo_data = $claude->optimize_for_seo( $title, $content );

                if ( $seo_data ) {
                    $final_title   = $seo_data['seo_title']         ?? $title;
                    $final_content = $seo_data['optimized_content']  ?? $content;
                    $final_slug    = $seo_data['slug']               ?? '';

                    Database::update_pipeline( $pipeline_id, [
                        'seo_data'          => wp_json_encode( $seo_data ),
                        'processed_content' => $final_content,
                    ] );

                    Logger::info( 'Claude SEO optimizasyonu tamamlandı.', 'pipeline', null, $pipeline_id );
                } else {
                    Logger::warning( 'Claude API yanıt vermedi, ham içerik kullanılacak.', 'pipeline', null, $pipeline_id );
                }
            }

            /* ---- Step 3: Find schedule slot ---- */
            Database::update_pipeline( $pipeline_id, [ 'step' => 'scheduling' ] );

            $slot = Scheduler::find_next_slot();

            /* ---- Step 4: Create WP post ---- */
            Database::update_pipeline( $pipeline_id, [ 'step' => 'create_post' ] );

            $author_id   = (int) get_option( 'hyt_schedule_author', 1 );
            $category_id = (int) get_option( 'hyt_schedule_category', 0 );

            $post_data = [
                'post_title'   => wp_strip_all_tags( $final_title ),
                'post_content' => $final_content,
                'post_status'  => 'future',
                'post_date'    => $slot->format( 'Y-m-d H:i:s' ),
                'post_author'  => $author_id ?: 1,
                'post_type'    => 'post',
            ];

            if ( $final_slug ) {
                $post_data['post_name'] = sanitize_title( $final_slug );
            }

            if ( $category_id ) {
                $post_data['post_category'] = [ $category_id ];
            }

            $post_id = wp_insert_post( $post_data, true );

            if ( is_wp_error( $post_id ) ) {
                throw new \RuntimeException( 'WP post oluşturulamadı: ' . $post_id->get_error_message() );
            }

            /* ---- Post meta (Yoast + custom) ---- */
            if ( $seo_data ) {
                $meta_desc     = $seo_data['meta_description'] ?? '';
                $focus_kw      = $seo_data['focus_keyword']    ?? '';

                // Yoast SEO compatibility
                if ( $meta_desc ) {
                    update_post_meta( $post_id, '_yoast_wpseo_metadesc', $meta_desc );
                }
                if ( $focus_kw ) {
                    update_post_meta( $post_id, '_yoast_wpseo_focuskw', $focus_kw );
                }
                if ( $final_title ) {
                    update_post_meta( $post_id, '_yoast_wpseo_title', $final_title );
                }

                // HYT custom meta
                update_post_meta( $post_id, '_hyt_meta_description', $meta_desc );
                update_post_meta( $post_id, '_hyt_focus_keyword', $focus_kw );
                update_post_meta( $post_id, '_hyt_seo_data', wp_json_encode( $seo_data ) );

                // FAQ schema if present
                if ( ! empty( $seo_data['faq_schema'] ) ) {
                    update_post_meta( $post_id, '_hyt_faq_schema', wp_json_encode( $seo_data['faq_schema'] ) );
                }
            }

            /* ---- Update pipeline record ---- */
            Database::update_pipeline( $pipeline_id, [
                'status'      => 'scheduled',
                'step'        => 'done',
                'post_id'     => $post_id,
                'scheduled_at'=> $slot->format( 'Y-m-d H:i:s' ),
            ] );

            Logger::info(
                sprintf( 'İçerik planlandı: %s → %s', $item->file_name, $slot->format( 'Y-m-d H:i' ) ),
                'pipeline',
                [ 'post_id' => $post_id, 'scheduled_at' => $slot->format( 'Y-m-d H:i:s' ) ],
                $pipeline_id
            );

        } catch ( \Throwable $e ) {
            Database::update_pipeline( $pipeline_id, [
                'status'        => 'failed',
                'step'          => 'error',
                'error_message' => $e->getMessage(),
            ] );
            Logger::error(
                'Pipeline hatası: ' . $e->getMessage(),
                'pipeline',
                [ 'trace' => $e->getTraceAsString() ],
                $pipeline_id
            );
        }
    }

    /**
     * Process an uploaded file: parse content, insert pipeline record.
     *
     * @return int Pipeline ID
     * @throws \RuntimeException on parse failure.
     */
    public function process_upload( string $file_path, string $file_name, string $source = 'manual' ): int {
        $extension = strtolower( pathinfo( $file_name, PATHINFO_EXTENSION ) );

        if ( $extension === 'docx' ) {
            $raw_content = $this->parse_docx( $file_path );
        } elseif ( $extension === 'txt' ) {
            $raw_content = (string) file_get_contents( $file_path );
        } else {
            throw new \RuntimeException( "Desteklenmeyen dosya türü: {$extension}" );
        }

        $raw_content = $this->clean_content( $raw_content );

        if ( empty( $raw_content ) ) {
            throw new \RuntimeException( "Dosya içeriği boş: {$file_name}" );
        }

        $title      = $this->extract_title( $raw_content, $file_name );
        $word_count = str_word_count( $raw_content );

        $pipeline_id = Database::insert_pipeline( [
            'source'         => $source,
            'file_name'      => substr( $file_name, 0, 500 ),
            'original_title' => substr( $title, 0, 500 ),
            'status'         => 'pending',
            'step'           => '',
            'word_count'     => $word_count,
            'raw_content'    => $raw_content,
        ] );

        if ( ! $pipeline_id ) {
            throw new \RuntimeException( "Veritabanına eklenemedi: {$file_name}" );
        }

        Logger::info( "Dosya kuyruğa eklendi: {$file_name}", 'upload', null, $pipeline_id );

        return $pipeline_id;
    }

    /* -----------------------------------------------------------------------
     * Private helpers
     * --------------------------------------------------------------------- */

    private function parse_docx( string $file_path ): string {
        if ( ! class_exists( 'ZipArchive' ) ) {
            throw new \RuntimeException( 'ZipArchive PHP eklentisi bulunamadı.' );
        }

        $zip = new \ZipArchive();
        if ( $zip->open( $file_path ) !== true ) {
            throw new \RuntimeException( "DOCX dosyası açılamadı: {$file_path}" );
        }

        $xml = $zip->getFromName( 'word/document.xml' );
        $zip->close();

        if ( $xml === false ) {
            throw new \RuntimeException( 'word/document.xml içinde bulunamadı.' );
        }

        // Load and parse XML
        libxml_use_internal_errors( true );
        $dom = new \DOMDocument();
        $dom->loadXML( $xml, LIBXML_NOERROR | LIBXML_NOWARNING );
        libxml_clear_errors();

        $ns    = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
        $paras = $dom->getElementsByTagNameNS( $ns, 'p' );

        $lines = [];
        foreach ( $paras as $para ) {
            $text = trim( $para->textContent );
            if ( $text !== '' ) {
                $lines[] = $text;
            }
        }

        return implode( "\n\n", $lines );
    }

    private function clean_content( string $content ): string {
        // Normalize line endings
        $content = str_replace( "\r\n", "\n", $content );
        $content = str_replace( "\r", "\n", $content );
        // Remove null bytes
        $content = str_replace( "\0", '', $content );
        // Trim excessive whitespace
        $content = preg_replace( '/\n{3,}/', "\n\n", $content ) ?? $content;
        return trim( $content );
    }

    /**
     * Extract title from content (first H1 / first line) or filename.
     */
    private function extract_title( string $content, string $file_name ): string {
        // Try to find first heading-like line (all caps or starts with #)
        $lines = array_filter( explode( "\n", $content ) );
        foreach ( $lines as $line ) {
            $line = trim( $line );
            if ( strlen( $line ) > 5 && strlen( $line ) < 200 ) {
                return $line;
            }
        }

        // Fallback: use file name without extension
        $name = pathinfo( $file_name, PATHINFO_FILENAME );
        $name = str_replace( [ '-', '_' ], ' ', $name );
        return ucfirst( $name );
    }
}
