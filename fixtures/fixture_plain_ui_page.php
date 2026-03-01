<?php
/**
 * Plain PHP UI page fixture.
 *
 * Expected score: 0-5
 *   - <html literal         → negative  -20
 *   - include header.php    → negative  -10
 *   - include footer.php    → negative  -10
 *   - echo "<div>"          → negative   -5
 *   No positive signals.
 *   Total before clamp: -45 → clamped to 0
 */

$pageTitle = "Welcome to Our Site";
$items = ["Product A", "Product B", "Product C"];

// Include site header (negative signal: include header.php)
include 'views/header.php';

?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title><?php echo htmlspecialchars($pageTitle); ?></title>
</head>
<body>

<div class="container">
    <h1><?php echo htmlspecialchars($pageTitle); ?></h1>

    <p>Welcome to our homepage. This is a standard web page, not an API endpoint.</p>

    <ul>
<?php foreach ($items as $item): ?>
        <li><?php echo htmlspecialchars($item); ?></li>
<?php endforeach; ?>
    </ul>

    <?php
    // Render a content section (negative: echo HTML)
    echo "<div class='content'>";
    echo "<p>This paragraph is generated via echo with an HTML tag.</p>";
    echo "</div>";
    ?>

</div>

</body>
</html>

<?php
// Include site footer (negative signal: include footer.php)
include 'views/footer.php';
?>
