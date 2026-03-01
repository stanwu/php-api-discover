# Test Plan for Tool A (PHP API Feature Extractor)

This document outlines a minimal test plan to verify the core functionality of `tool_a`. The primary method of testing is to create a small, representative PHP project with known features and run the tool against it, then inspect the output reports.

## Test Project Setup

Create a directory structure with a few PHP files containing various patterns the tool should detect.

**Directory Structure:**

```
test_project/
├───api/
│   ├───user.php
│   └───product.php
├───lib/
│   └───helpers.php
├───views/
│   ├───header.php
│   └───home.phtml
├───vendor/
│   └───some_lib.php
└───index.php
```

### File Contents

#### `api/user.php` (High Score Candidate)
```php
<?php
// Should have a high score
header('Content-Type: application/json');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    die(json_encode(['error' => 'Method Not Allowed']));
}

$input = json_decode(file_get_contents('php://input'), true);

$userId = $_GET['id'] ?? null;
$token = $_POST['token'] ?? 'default';

$response = [
    'success' => true,
    'data' => [
        'user_id' => $userId,
        'name' => 'John Doe',
        'email' => 'john.doe@example.com',
        'received_token' => !empty($token),
        'input_key' => $input['some_key'] ?? null,
    ],
    'code' => 200,
    'secret' => 'a_password_value'
];

// A secret to be redacted
$config['api_key'] = 'super_secret_api_key_12345';

echo json_encode($response);
```

#### `api/product.php` (Medium Score Candidate)
```php
<?php
// Should have a medium score, uses a custom helper
require_once '../lib/helpers.php';

$productId = $_REQUEST['product_id'];

// Simulate fetching a product
$product = [
    'id' => $productId,
    'name' => 'Awesome Gadget',
    'price' => 99.99
];

// Uses a custom helper function
returnJson($product);
```

#### `lib/helpers.php`
```php
<?php
// A helper library, should have a low score
function returnJson(array $data, int $statusCode = 200) {
    http_response_code($statusCode);
    // This file itself isn't an endpoint, but contains a strong signal
    echo json_encode(['status' => 'ok', 'result' => $data]);
}
```

#### `index.php` (Negative Score Candidate)
```php
<?php
// Should have a very low score due to HTML
$pageTitle = "Welcome";
include 'views/header.php';
?>

<div class="container">
    <h1>Welcome to our Homepage</h1>
    <p>This is a standard web page, not an API.</p>
</div>

<?php include 'views/footer.php'; // Assume footer.php exists ?>
```

#### `views/home.phtml` (Negative Score Candidate)
```html
<!DOCTYPE html>
<html>
<head>
    <title>My App</title>
</head>
<body>
    <p>This is a phtml file and should be ignored by default, or scored negatively if included.</p>
</body>
</html>
```

#### `vendor/some_lib.php`
```php
<?php
// This file should be ignored by default.
echo "This is a vendor file.";
```

## Test Execution

1.  Create the `test_project` directory and the files as described above.
2.  Run `tool_a` against this project.

    ```bash
    python tool_a.py scan --root ./test_project --out test_report.md --raw test_features.jsonl
    ```

## Verification Steps

### 1. `test_report.md` Inspection

-   **Summary Stats:**
    -   Verify that `vendor/` was excluded.
    -   Check that the file counts are correct.
    -   Check if top signals (`header`, `json_encode`, `$_GET`, etc.) and their frequencies seem correct.
-   **`api/user.php`:**
    -   Should have a **high score** (e.g., > 80).
    -   **Signals:** Should list `header('Content-Type: application/json')`, `die(json_encode(...))`, `json_encode`, `php://input`.
    -   **Parameters:** Should detect `$_GET['id']`, `$_POST['token']`. It should hint at `some_key` from `$input['some_key']`.
    -   **Method Hints:** Should detect `POST`.
    -   **Envelope Keys:** Should detect `success`, `data`, `code`, `error`, `secret`.
    -   **Snippets:** Should show the `die(json_encode(...))` and `echo json_encode($response)` lines. The `$config['api_key']` value should be `REDACTED`. The `'secret' => 'a_password_value'` should also be `REDACTED`.
-   **`api/product.php`:**
    -   Should have a **medium-to-high score** (e.g., > 65).
    -   **Signals:** Should list `custom json helper` (`returnJson`).
    -   **Parameters:** Should detect `$_REQUEST['product_id']`.
    -   **Snippets:** Should show the `returnJson(...)` call.
-   **`index.php`:**
    -   Should have a **low score** (e.g., < 40).
    -   **Signals:** Should list negative signals like `include .../view...` and `HTML tag`.
-   **`lib/helpers.php`:**
    -   Score could be ambiguous. It has a strong `json_encode` signal but no input signals. It should likely be lower than the actual endpoint files. The report should make it clear why it was scored that way.
-   **`views/home.phtml`:**
    -   Should not appear in the report unless `--extensions .php .phtml` is used. If it is, it should have a very low score due to HTML tags.

### 2. `test_features.jsonl` Inspection

-   Open the file and check that each line is valid JSON.
-   Verify that the data for each file corresponds to the findings in the Markdown report.
-   Check that the structure matches the spec (`path`, `score`, `signals`, `input_params`, etc.).

### 3. Edge Case Testing

-   Run the tool with `--exclude api` to ensure the `api` directory is skipped.
-   Run with `--max-files 1` to ensure it stops after one file.
-   Create an empty PHP file and ensure it's processed without errors and gets a neutral/low score.
-   Create a very large file (> 5MB by default) and ensure it's skipped with a message.
