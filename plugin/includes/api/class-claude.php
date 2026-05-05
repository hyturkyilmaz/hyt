<?php

declare(strict_types=1);

namespace HYT\Api;

use HYT\Logger;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Claude {

    private string $api_key;
    private string $model;
    private string $api_url = 'https://api.anthropic.com/v1/messages';

    public function __construct() {
        $this->api_key = (string) get_option( 'hyt_claude_api_key', '' );
        $this->model   = (string) get_option( 'hyt_claude_model', 'claude-sonnet-4-5' );
    }

    public function is_configured(): bool {
        return ! empty( $this->api_key );
    }

    /**
     * Optimize content for SEO/GEO using Claude API.
     *
     * @return array<string,mixed>|null Returns SEO data array or null on failure.
     */
    public function optimize_for_seo( string $title, string $content ): ?array {
        if ( ! $this->is_configured() ) {
            return null;
        }

        $word_count = str_word_count( $content );
        $excerpt    = mb_substr( $content, 0, 3000 );

        $prompt = <<<PROMPT
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
    {"question": "Soru 2?", "answer": "Cevap 2"},
    {"question": "Soru 3?", "answer": "Cevap 3"}
  ],
  "geo_summary": "GEO (Generative Engine Optimization) için 2-3 cümlelik, yetkili ve yapılandırılmış özet",
  "optimized_content": "HTML formatında optimize edilmiş içerik. H2 ve H3 başlıklar kullan, paragrafları düzenle, listeleri ekle. İçeriği SEO açısından zenginleştir."
}

Kurallar:
- seo_title kesinlikle 50-60 karakter arası olmalı
- meta_description kesinlikle 155 karakteri geçmemeli
- slug sadece küçük harf, rakam ve tire içermeli
- optimized_content orijinal içeriğin SEO optimize edilmiş HTML versiyonu olmalı
- Tüm metin Türkçe olmalı
PROMPT;

        $body = [
            'model'      => $this->model,
            'max_tokens' => 4096,
            'messages'   => [
                [
                    'role'    => 'user',
                    'content' => $prompt,
                ],
            ],
        ];

        $response = wp_remote_post( $this->api_url, [
            'timeout' => 180,
            'headers' => [
                'Content-Type'      => 'application/json',
                'x-api-key'         => $this->api_key,
                'anthropic-version' => '2023-06-01',
            ],
            'body'    => wp_json_encode( $body ),
        ] );

        if ( is_wp_error( $response ) ) {
            Logger::error(
                'Claude API bağlantı hatası: ' . $response->get_error_message(),
                'claude_api'
            );
            return null;
        }

        $http_code = wp_remote_retrieve_response_code( $response );
        $raw_body  = wp_remote_retrieve_body( $response );

        if ( $http_code !== 200 ) {
            Logger::error(
                "Claude API HTTP hatası: {$http_code}",
                'claude_api',
                [ 'response' => $raw_body ]
            );
            return null;
        }

        $data = json_decode( $raw_body, true );

        if ( ! isset( $data['content'][0]['text'] ) ) {
            Logger::error(
                'Claude API beklenmeyen yanıt formatı',
                'claude_api',
                [ 'raw' => $raw_body ]
            );
            return null;
        }

        $text = $data['content'][0]['text'];

        // Extract JSON from response (Claude might add markdown code blocks)
        $json_text = $this->extract_json( $text );

        $seo_data = json_decode( $json_text, true );

        if ( ! is_array( $seo_data ) ) {
            Logger::error(
                'Claude API JSON parse hatası',
                'claude_api',
                [ 'text' => $text ]
            );
            return null;
        }

        return $seo_data;
    }

    /**
     * Test Claude API connection.
     *
     * @return array{success: bool, message: string}
     */
    public function test_connection(): array {
        if ( ! $this->is_configured() ) {
            return [ 'success' => false, 'message' => 'API anahtarı girilmemiş.' ];
        }

        $response = wp_remote_post( $this->api_url, [
            'timeout' => 30,
            'headers' => [
                'Content-Type'      => 'application/json',
                'x-api-key'         => $this->api_key,
                'anthropic-version' => '2023-06-01',
            ],
            'body'    => wp_json_encode( [
                'model'      => $this->model,
                'max_tokens' => 50,
                'messages'   => [
                    [ 'role' => 'user', 'content' => 'Merhaba, bağlantı testi. Sadece "OK" yaz.' ],
                ],
            ] ),
        ] );

        if ( is_wp_error( $response ) ) {
            return [ 'success' => false, 'message' => $response->get_error_message() ];
        }

        $http_code = wp_remote_retrieve_response_code( $response );

        if ( $http_code === 200 ) {
            return [ 'success' => true, 'message' => 'Bağlantı başarılı! Model: ' . $this->model ];
        }

        $body = json_decode( wp_remote_retrieve_body( $response ), true );
        $msg  = $body['error']['message'] ?? "HTTP {$http_code}";
        return [ 'success' => false, 'message' => $msg ];
    }

    /**
     * Extract JSON string from Claude response (may contain markdown code fences).
     */
    private function extract_json( string $text ): string {
        // Try to extract from ```json ... ``` blocks
        if ( preg_match( '/```(?:json)?\s*(\{.*?\})\s*```/s', $text, $matches ) ) {
            return $matches[1];
        }

        // Try to find raw JSON object
        if ( preg_match( '/\{.*\}/s', $text, $matches ) ) {
            return $matches[0];
        }

        return $text;
    }
}
