<?php

declare(strict_types=1);

namespace HYT\Api;

use HYT\Logger;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Google_Drive {

    private const TOKEN_OPTION    = 'hyt_gdrive_token';
    private const SCANNED_OPTION  = 'hyt_gdrive_scanned_files';
    private const AUTH_URL        = 'https://accounts.google.com/o/oauth2/v2/auth';
    private const TOKEN_URL       = 'https://oauth2.googleapis.com/token';
    private const DRIVE_API_BASE  = 'https://www.googleapis.com/drive/v3';
    private const DRIVE_DL_BASE   = 'https://www.googleapis.com/drive/v3/files';

    private string $client_id;
    private string $client_secret;
    private string $folder_id;

    public function __construct() {
        $this->client_id     = (string) get_option( 'hyt_gdrive_client_id', '' );
        $this->client_secret = (string) get_option( 'hyt_gdrive_client_secret', '' );
        $this->folder_id     = (string) get_option( 'hyt_gdrive_folder_id', '' );
    }

    public function is_configured(): bool {
        return ! empty( $this->client_id ) && ! empty( $this->client_secret );
    }

    public function is_connected(): bool {
        $token = $this->get_token();
        return ! empty( $token['access_token'] );
    }

    /**
     * Build OAuth2 authorization URL.
     */
    public function get_auth_url(): string {
        $redirect_uri = $this->get_redirect_uri();

        $params = [
            'client_id'             => $this->client_id,
            'redirect_uri'          => $redirect_uri,
            'response_type'         => 'code',
            'scope'                 => 'https://www.googleapis.com/auth/drive.readonly',
            'access_type'           => 'offline',
            'prompt'                => 'consent',
            'state'                 => wp_create_nonce( 'hyt_gdrive_oauth' ),
        ];

        return self::AUTH_URL . '?' . http_build_query( $params );
    }

    /**
     * Handle OAuth2 callback (REST endpoint).
     */
    public function handle_callback( \WP_REST_Request $request ): void {
        $code  = sanitize_text_field( $request->get_param( 'code' ) ?? '' );
        $state = sanitize_text_field( $request->get_param( 'state' ) ?? '' );

        if ( ! $code ) {
            wp_die( 'Yetkilendirme kodu eksik.' );
        }

        if ( ! wp_verify_nonce( $state, 'hyt_gdrive_oauth' ) ) {
            wp_die( 'Güvenlik doğrulaması başarısız.' );
        }

        $token = $this->exchange_code_for_token( $code );

        if ( $token && ! empty( $token['access_token'] ) ) {
            $token['created_at'] = time();
            update_option( self::TOKEN_OPTION, $token );
            Logger::info( 'Google Drive OAuth2 bağlantısı başarılı.', 'gdrive' );
            wp_safe_redirect( admin_url( 'admin.php?page=hyt-ca-settings&tab=gdrive&connected=1' ) );
            exit;
        }

        wp_safe_redirect( admin_url( 'admin.php?page=hyt-ca-settings&tab=gdrive&error=1' ) );
        exit;
    }

    /**
     * Exchange authorization code for access/refresh token.
     *
     * @return array<string,mixed>|null
     */
    private function exchange_code_for_token( string $code ): ?array {
        $response = wp_remote_post( self::TOKEN_URL, [
            'timeout' => 30,
            'body'    => [
                'code'          => $code,
                'client_id'     => $this->client_id,
                'client_secret' => $this->client_secret,
                'redirect_uri'  => $this->get_redirect_uri(),
                'grant_type'    => 'authorization_code',
            ],
        ] );

        if ( is_wp_error( $response ) ) {
            Logger::error( 'Token değişimi hatası: ' . $response->get_error_message(), 'gdrive' );
            return null;
        }

        $data = json_decode( wp_remote_retrieve_body( $response ), true );
        return is_array( $data ) ? $data : null;
    }

    /**
     * Refresh the access token using stored refresh token.
     */
    public function refresh_token(): bool {
        $token = $this->get_token();

        if ( empty( $token['refresh_token'] ) ) {
            Logger::error( 'Refresh token mevcut değil.', 'gdrive' );
            return false;
        }

        $response = wp_remote_post( self::TOKEN_URL, [
            'timeout' => 30,
            'body'    => [
                'refresh_token' => $token['refresh_token'],
                'client_id'     => $this->client_id,
                'client_secret' => $this->client_secret,
                'grant_type'    => 'refresh_token',
            ],
        ] );

        if ( is_wp_error( $response ) ) {
            Logger::error( 'Token yenileme hatası: ' . $response->get_error_message(), 'gdrive' );
            return false;
        }

        $new_token = json_decode( wp_remote_retrieve_body( $response ), true );

        if ( ! empty( $new_token['access_token'] ) ) {
            $new_token['refresh_token'] = $token['refresh_token']; // keep refresh token
            $new_token['created_at']    = time();
            update_option( self::TOKEN_OPTION, $new_token );
            return true;
        }

        return false;
    }

    /**
     * Scan Google Drive folder for .docx, .txt, and Google Docs files.
     *
     * @return array<array<string,string>> List of file info arrays.
     */
    public function scan_folder( ?string $folder_id = null ): array {
        $folder_id = $folder_id ?: $this->folder_id;

        if ( ! $folder_id ) {
            Logger::error( 'Klasör ID girilmemiş.', 'gdrive' );
            return [];
        }

        $access_token = $this->get_valid_access_token();
        if ( ! $access_token ) {
            return [];
        }

        $scanned_ids = (array) get_option( self::SCANNED_OPTION, [] );
        $files       = [];
        $page_token  = null;

        // MIME types we care about
        $mime_query = implode( ' or ', [
            "mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'",
            "mimeType='text/plain'",
            "mimeType='application/vnd.google-apps.document'",
        ] );

        do {
            $params = [
                'q'        => "'{$folder_id}' in parents and ({$mime_query}) and trashed=false",
                'fields'   => 'nextPageToken,files(id,name,mimeType,modifiedTime)',
                'pageSize' => 100,
            ];

            if ( $page_token ) {
                $params['pageToken'] = $page_token;
            }

            $url      = self::DRIVE_API_BASE . '/files?' . http_build_query( $params );
            $response = $this->api_get( $url, $access_token );

            if ( ! $response ) {
                break;
            }

            foreach ( $response['files'] ?? [] as $file ) {
                if ( ! in_array( $file['id'], $scanned_ids, true ) ) {
                    $files[] = $file;
                }
            }

            $page_token = $response['nextPageToken'] ?? null;

        } while ( $page_token );

        return $files;
    }

    /**
     * Read and return plain-text content of a Drive file.
     */
    public function read_file( string $file_id, string $mime_type ): ?string {
        $access_token = $this->get_valid_access_token();
        if ( ! $access_token ) {
            return null;
        }

        try {
            if ( $mime_type === 'application/vnd.google-apps.document' ) {
                // Export Google Doc as plain text
                $url     = self::DRIVE_DL_BASE . "/{$file_id}/export?mimeType=text/plain";
                $content = $this->download_file( $url, $access_token );
            } elseif ( $mime_type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ) {
                // Download docx then parse
                $url      = self::DRIVE_DL_BASE . "/{$file_id}?alt=media";
                $tmp_path = $this->download_to_tmp( $url, $access_token, $file_id . '.docx' );
                if ( ! $tmp_path ) {
                    return null;
                }
                $content = $this->parse_docx( $tmp_path );
                @unlink( $tmp_path );
            } else {
                // Plain text
                $url     = self::DRIVE_DL_BASE . "/{$file_id}?alt=media";
                $content = $this->download_file( $url, $access_token );
            }

            return $content ?: null;
        } catch ( \Throwable $e ) {
            Logger::error( 'Dosya okuma hatası: ' . $e->getMessage(), 'gdrive', [ 'file_id' => $file_id ] );
            return null;
        }
    }

    /**
     * Mark a file as scanned.
     */
    public function mark_scanned( string $file_id ): void {
        $scanned = (array) get_option( self::SCANNED_OPTION, [] );
        $scanned[] = $file_id;
        update_option( self::SCANNED_OPTION, array_unique( $scanned ) );
    }

    /**
     * Disconnect: remove stored token.
     */
    public function disconnect(): void {
        delete_option( self::TOKEN_OPTION );
        Logger::info( 'Google Drive bağlantısı kesildi.', 'gdrive' );
    }

    /**
     * Parse .docx file and extract plain text.
     */
    public function parse_docx( string $file_path ): string {
        if ( ! class_exists( 'ZipArchive' ) ) {
            throw new \RuntimeException( 'ZipArchive PHP eklentisi bulunamadı.' );
        }

        $zip = new \ZipArchive();

        if ( $zip->open( $file_path ) !== true ) {
            throw new \RuntimeException( 'DOCX dosyası açılamadı: ' . $file_path );
        }

        $xml_content = $zip->getFromName( 'word/document.xml' );
        $zip->close();

        if ( $xml_content === false ) {
            throw new \RuntimeException( 'word/document.xml bulunamadı.' );
        }

        return $this->parse_docx_xml( $xml_content );
    }

    /**
     * Parse word/document.xml and return clean text.
     */
    private function parse_docx_xml( string $xml_content ): string {
        // Load XML
        $dom = new \DOMDocument();
        $dom->loadXML( $xml_content, LIBXML_NOERROR | LIBXML_NOWARNING );

        $paragraphs = $dom->getElementsByTagNameNS(
            'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
            'p'
        );

        $lines = [];
        foreach ( $paragraphs as $para ) {
            $text = $para->textContent;
            $text = trim( $text );
            if ( $text !== '' ) {
                $lines[] = $text;
            }
        }

        return implode( "\n\n", $lines );
    }

    /* -----------------------------------------------------------------------
     * Private helpers
     * --------------------------------------------------------------------- */

    /**
     * Get stored token data.
     *
     * @return array<string,mixed>
     */
    private function get_token(): array {
        return (array) get_option( self::TOKEN_OPTION, [] );
    }

    /**
     * Get a valid access token, refreshing if expired.
     */
    private function get_valid_access_token(): ?string {
        $token = $this->get_token();

        if ( empty( $token['access_token'] ) ) {
            Logger::error( 'Erişim tokeni bulunamadı. Google Drive bağlanılmamış.', 'gdrive' );
            return null;
        }

        // Check expiry: expires_in is seconds, created_at is Unix timestamp
        $expires_at = ( $token['created_at'] ?? 0 ) + ( $token['expires_in'] ?? 3600 ) - 60;
        if ( time() > $expires_at ) {
            if ( ! $this->refresh_token() ) {
                return null;
            }
            $token = $this->get_token();
        }

        return $token['access_token'];
    }

    /**
     * Make an authenticated GET request to Drive API.
     *
     * @return array<string,mixed>|null
     */
    private function api_get( string $url, string $access_token ): ?array {
        $response = wp_remote_get( $url, [
            'timeout' => 30,
            'headers' => [
                'Authorization' => 'Bearer ' . $access_token,
            ],
        ] );

        if ( is_wp_error( $response ) ) {
            Logger::error( 'Drive API isteği başarısız: ' . $response->get_error_message(), 'gdrive' );
            return null;
        }

        $code = wp_remote_retrieve_response_code( $response );
        if ( $code !== 200 ) {
            Logger::error( "Drive API HTTP {$code} hatası.", 'gdrive', [ 'url' => $url ] );
            return null;
        }

        return json_decode( wp_remote_retrieve_body( $response ), true );
    }

    /**
     * Download file content as string.
     */
    private function download_file( string $url, string $access_token ): ?string {
        $response = wp_remote_get( $url, [
            'timeout' => 60,
            'headers' => [ 'Authorization' => 'Bearer ' . $access_token ],
        ] );

        if ( is_wp_error( $response ) ) {
            return null;
        }

        return wp_remote_retrieve_body( $response ) ?: null;
    }

    /**
     * Download file to a temp path.
     */
    private function download_to_tmp( string $url, string $access_token, string $filename ): ?string {
        $uploads  = wp_upload_dir();
        $tmp_dir  = $uploads['basedir'] . '/hyt-tmp/';
        wp_mkdir_p( $tmp_dir );

        $tmp_path = $tmp_dir . sanitize_file_name( $filename );

        $response = wp_remote_get( $url, [
            'timeout' => 120,
            'headers' => [ 'Authorization' => 'Bearer ' . $access_token ],
            'stream'  => true,
            'filename'=> $tmp_path,
        ] );

        if ( is_wp_error( $response ) || wp_remote_retrieve_response_code( $response ) !== 200 ) {
            return null;
        }

        return $tmp_path;
    }

    /**
     * Build the OAuth2 redirect URI pointing to our REST endpoint.
     */
    private function get_redirect_uri(): string {
        return rest_url( 'hyt/v1/gdrive-callback' );
    }

    /**
     * Static callback entry point (for rest_api_init registration).
     */
    public static function handle_oauth_callback( \WP_REST_Request $request ): void {
        ( new self() )->handle_callback( $request );
    }
}
