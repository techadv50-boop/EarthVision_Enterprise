<?php
declare(strict_types=1);
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$root = dirname(__DIR__);

// API
if (str_starts_with($uri, '/api')) {
    require $root . '/api/index.php';
    return true;
}

// Static frontend from dist
$dist = $root . '/frontend/dist';
$path = $dist . ($uri === '/' ? '/index.html' : $uri);
if ($uri !== '/' && is_file($path)) {
    $ext = pathinfo($path, PATHINFO_EXTENSION);
    $types = [
        'html' => 'text/html',
        'js' => 'application/javascript',
        'css' => 'text/css',
        'svg' => 'image/svg+xml',
        'png' => 'image/png',
        'jpg' => 'image/jpeg',
        'ico' => 'image/x-icon',
        'json' => 'application/json',
        'map' => 'application/json',
        'woff' => 'font/woff',
        'woff2' => 'font/woff2',
        'zip' => 'application/zip',
    ];
    header('Content-Type: ' . ($types[$ext] ?? 'application/octet-stream'));
    if ($ext === 'zip') {
        header('Content-Disposition: attachment; filename="' . basename($path) . '"');
        header('Content-Length: ' . (string) filesize($path));
    }
    readfile($path);
    return true;
}

// SPA fallback
header('Content-Type: text/html; charset=utf-8');
readfile($dist . '/index.html');
return true;
