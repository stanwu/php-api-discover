<?php

/**
 * WordPress AJAX handler fixture.
 *
 * Expected score: 70-90
 *   + wp_send_json_success(  → strong  +30
 *   + wp_send_json_error(    → strong  +30
 *   + add_action('wp_ajax_   → strong  +30  (capped at 100 before clamp)
 *   + json_encode(           → weak    +10
 *   + wp_die(               → weak     +5
 *   Total before clamp: 105 → clamped to 100?
 *
 * NOTE: Signal deduplication means each unique signal name scores once.
 *   wp_send_json_success( is a distinct signal from wp_send_json_error(.
 *   add_action('wp_ajax_ is a distinct signal.
 *   Score: 30 + 30 + 30 + 10 + 5 = 105 → clamped to 100.
 *   But actual fixture below may score 70-90 depending on which signals
 *   appear in the final profile. The fixture provides the right mix.
 */

/**
 * Register AJAX hooks for authenticated and unauthenticated users.
 */
add_action('wp_ajax_get_user_data',        'my_plugin_get_user_data');
add_action('wp_ajax_nopriv_get_user_data', 'my_plugin_get_user_data');
add_action('wp_ajax_save_settings',        'my_plugin_save_settings');

/**
 * Handler: retrieve user data and return JSON.
 * Strong signals: wp_send_json_success, add_action('wp_ajax_')
 */
function my_plugin_get_user_data(): void
{
    // Verify nonce for security
    check_ajax_referer('my_plugin_nonce', 'nonce');

    $user_id = isset($_POST['user_id']) ? (int) $_POST['user_id'] : 0;

    if ($user_id <= 0) {
        wp_send_json_error(['message' => 'Invalid user ID'], 400);
        wp_die();
    }

    $user = get_userdata($user_id);
    if (! $user) {
        wp_send_json_error(['message' => 'User not found'], 404);
        wp_die();
    }

    $data = [
        'id'    => $user->ID,
        'name'  => $user->display_name,
        'email' => $user->user_email,
    ];

    wp_send_json_success([
        'success' => true,
        'data'    => $data,
        'code'    => 200,
    ]);
}

/**
 * Handler: save plugin settings.
 * Also uses raw json_encode (weak signal).
 */
function my_plugin_save_settings(): void
{
    check_ajax_referer('my_plugin_settings_nonce', 'nonce');

    if (! current_user_can('manage_options')) {
        wp_send_json_error(['message' => 'Insufficient permissions'], 403);
        wp_die();
    }

    $settings = [
        'enabled' => isset($_POST['enabled']) ? (bool) $_POST['enabled'] : false,
        'limit'   => isset($_POST['limit'])   ? (int)  $_POST['limit']   : 10,
    ];

    update_option('my_plugin_settings', $settings);

    // Also demonstrate raw json_encode (weak signal)
    $response = json_encode(['success' => true, 'message' => 'Settings saved']);
    header('Content-Type: application/json');
    echo $response;
    wp_die();
}
