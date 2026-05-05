<?php

declare(strict_types=1);

namespace HYT\Admin;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Admin_Menu {

    public function init(): void {
        add_action( 'admin_menu', [ $this, 'register_menus' ] );
        add_action( 'admin_enqueue_scripts', [ $this, 'enqueue_assets' ] );
    }

    public function register_menus(): void {
        $capability = 'manage_options';

        add_menu_page(
            'HYT İçerik Otomasyonu',
            'HYT İçerik',
            $capability,
            'hyt-ca-dashboard',
            [ $this, 'render_dashboard' ],
            'dashicons-admin-post',
            30
        );

        add_submenu_page(
            'hyt-ca-dashboard',
            'Dashboard',
            'Dashboard',
            $capability,
            'hyt-ca-dashboard',
            [ $this, 'render_dashboard' ]
        );

        add_submenu_page(
            'hyt-ca-dashboard',
            'Kuyruk',
            'Kuyruk',
            $capability,
            'hyt-ca-queue',
            [ $this, 'render_queue' ]
        );

        add_submenu_page(
            'hyt-ca-dashboard',
            'Loglar',
            'Loglar',
            $capability,
            'hyt-ca-logs',
            [ $this, 'render_logs' ]
        );

        add_submenu_page(
            'hyt-ca-dashboard',
            'Ayarlar',
            'Ayarlar',
            $capability,
            'hyt-ca-settings',
            [ $this, 'render_settings' ]
        );
    }

    public function enqueue_assets( string $hook ): void {
        $plugin_pages = [
            'toplevel_page_hyt-ca-dashboard',
            'hyt-içerik_page_hyt-ca-queue',
            'hyt-içerik_page_hyt-ca-logs',
            'hyt-içerik_page_hyt-ca-settings',
        ];

        // Also handle different sanitizations of the menu title
        if ( ! in_array( $hook, $plugin_pages, true ) && strpos( $hook, 'hyt-ca' ) === false ) {
            return;
        }

        wp_enqueue_style(
            'hyt-ca-admin',
            HYT_PLUGIN_URL . 'admin/css/style.css',
            [],
            HYT_VERSION
        );

        wp_enqueue_script(
            'hyt-ca-admin',
            HYT_PLUGIN_URL . 'admin/js/main.js',
            [ 'jquery' ],
            HYT_VERSION,
            true
        );

        wp_localize_script( 'hyt-ca-admin', 'hytCA', [
            'ajaxUrl'    => admin_url( 'admin-ajax.php' ),
            'nonce'      => wp_create_nonce( 'hyt_ajax_nonce' ),
            'pluginUrl'  => HYT_PLUGIN_URL,
            'currentPage'=> $this->get_current_page(),
            'strings'    => [
                'uploadSuccess'   => 'Dosyalar başarıyla yüklendi.',
                'uploadError'     => 'Yükleme sırasında hata oluştu.',
                'confirmCancel'   => 'Bu öğeyi iptal etmek istediğinizden emin misiniz?',
                'confirmRetry'    => 'Bu öğeyi yeniden işlemek istiyor musunuz?',
                'processing'      => 'İşleniyor...',
                'testingApi'      => 'API test ediliyor...',
                'saving'          => 'Kaydediliyor...',
                'saved'           => 'Ayarlar kaydedildi.',
            ],
        ] );
    }

    private function get_current_page(): string {
        return sanitize_key( $_GET['page'] ?? '' );
    }

    public function render_dashboard(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( 'Yetkiniz yok.' );
        }
        require HYT_PLUGIN_DIR . 'admin/views/dashboard.php';
    }

    public function render_queue(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( 'Yetkiniz yok.' );
        }
        require HYT_PLUGIN_DIR . 'admin/views/queue.php';
    }

    public function render_logs(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( 'Yetkiniz yok.' );
        }
        require HYT_PLUGIN_DIR . 'admin/views/logs.php';
    }

    public function render_settings(): void {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( 'Yetkiniz yok.' );
        }
        require HYT_PLUGIN_DIR . 'admin/views/settings.php';
    }
}
