<?php
/**
 * Plugin Name: HYT Content Automation
 * Plugin URI:  https://hyt.com.tr
 * Description: Toplu .docx yükleme, Google Drive entegrasyonu, Claude API SEO optimizasyonu ve akıllı zamanlama ile içerik otomasyonu.
 * Version:     1.0.0
 * Author:      HYT
 * Author URI:  https://hyt.com.tr
 * License:     GPL-2.0+
 * Requires at least: 6.2
 * Requires PHP: 8.1
 * Text Domain: hyt-content-automation
 */

declare(strict_types=1);

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

define( 'HYT_VERSION', '1.0.0' );
define( 'HYT_PLUGIN_FILE', __FILE__ );
define( 'HYT_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );
define( 'HYT_PLUGIN_URL', plugin_dir_url( __FILE__ ) );
define( 'HYT_PLUGIN_BASENAME', plugin_basename( __FILE__ ) );

/**
 * Autoloader
 */
spl_autoload_register( function ( string $class_name ): void {
    $prefix = 'HYT\\';
    if ( ! str_starts_with( $class_name, $prefix ) ) {
        return;
    }

    $relative = substr( $class_name, strlen( $prefix ) );
    $parts    = explode( '\\', $relative );
    $file     = 'class-' . strtolower( str_replace( '_', '-', array_pop( $parts ) ) ) . '.php';
    $dir      = strtolower( implode( DIRECTORY_SEPARATOR, $parts ) );

    $path = HYT_PLUGIN_DIR . 'includes' . ( $dir ? DIRECTORY_SEPARATOR . $dir : '' ) . DIRECTORY_SEPARATOR . $file;

    if ( file_exists( $path ) ) {
        require_once $path;
    }
} );

/**
 * Activation hook
 */
register_activation_hook( __FILE__, function (): void {
    require_once HYT_PLUGIN_DIR . 'includes/class-database.php';
    HYT\Database::create_tables();
    HYT\Scheduler::register_cron();
    flush_rewrite_rules();
} );

/**
 * Deactivation hook
 */
register_deactivation_hook( __FILE__, function (): void {
    wp_clear_scheduled_hook( 'hyt_process_queue' );
    flush_rewrite_rules();
} );

/**
 * Bootstrap
 */
add_action( 'plugins_loaded', function (): void {
    // Ensure DB tables exist (upgrade path)
    HYT\Database::create_tables();

    // Boot services
    HYT\Scheduler::register_cron();
    ( new HYT\Admin\Admin_Menu() )->init();
    ( new HYT\Admin\Ajax() )->init();

    // REST endpoint for Google OAuth callback
    add_action( 'rest_api_init', function (): void {
        register_rest_route( 'hyt/v1', '/gdrive-callback', [
            'methods'             => 'GET',
            'callback'            => [ HYT\Api\Google_Drive::class, 'handle_oauth_callback' ],
            'permission_callback' => '__return_true',
        ] );
    } );
} );

/**
 * Cron handler
 */
add_action( 'hyt_process_queue', function (): void {
    HYT\Scheduler::process_queue();
} );
