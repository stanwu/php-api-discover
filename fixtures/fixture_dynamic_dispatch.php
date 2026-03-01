<?php

/**
 * Dynamic dispatch fixture.
 *
 * Expected: weak signal flagged, dynamic note present in report.
 *   - Variable function call: $func = 'json_encode'; echo $func($data);
 *     → DynamicNote type "variable_dispatch" added
 *     → json_encode treated as weak signal (+10)
 *
 * Demonstrates the Dynamic Pattern Detector module.
 */

/**
 * Returns data using a variable-dispatch pattern.
 * The function to call is stored in a variable at runtime.
 */
function dispatchResponse(array $data): void
{
    // Variable assigned a known JSON function name
    $func = 'json_encode';

    // Variable called as a function — this is the dynamic dispatch
    $output = $func($data);

    header('Content-Type: application/json');
    echo $output;
    exit;
}

/**
 * Another example: concatenated Content-Type header (also dynamic).
 */
function sendWithConcatHeader(array $data): void
{
    $ct = 'application/' . 'json';
    header('Content-Type: ' . $ct);
    echo json_encode($data);
    exit;
}

// Simulate a simple API endpoint
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    $responseData = [
        'success' => true,
        'data'    => ['key' => 'value'],
        'message' => 'OK',
    ];
    dispatchResponse($responseData);
}
