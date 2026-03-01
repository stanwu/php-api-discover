<?php

/**
 * Secrets redaction fixture.
 *
 * Expected:
 *   - $api_key value is redacted (matches pattern 1: assignment with quoted value ≥ 8 chars)
 *   - redaction_count = 1
 *   - The key name "api_key" is preserved; only the value is replaced with REDACTED
 *
 * Also uses json_encode (weak signal) so it appears as a candidate file.
 */

// This long key value should be redacted by Pattern 1 (assignment with quoted value)
$api_key = 'abc123xyz456def789ghi012jkl345mn';

// Simulate an API response using the key
function getApiData(string $apiKey): array
{
    return [
        'success' => true,
        'data'    => [
            'key_prefix' => substr($apiKey, 0, 4) . '****',
            'result'     => 42,
        ],
        'message' => 'Data retrieved',
    ];
}

$response = getApiData($api_key);

header('Content-Type: application/json');
echo json_encode($response);
