<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function vox_config(): array
{
    static $config;
    if ($config === null) {
        $config = require __DIR__ . '/config.php';
    }
    return $config;
}

function vox_db(): PDO
{
    static $pdo;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    vox_ensure_dirs();
    $path = VOX_DATA . '/voxpersona.sqlite';
    $pdo = new PDO('sqlite:' . $path, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA foreign_keys = ON');
    vox_migrate($pdo);
    return $pdo;
}

function vox_migrate(PDO $pdo): void
{
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT "user",
            status TEXT NOT NULL DEFAULT "pending",
            subscription_ends_at TEXT,
            last_reminder_sent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            admin_note TEXT DEFAULT ""
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )'
    );

    $config = vox_config();
    $stmt = $pdo->prepare('SELECT id FROM users WHERE email = ? LIMIT 1');
    $stmt->execute([strtolower($config['admin_email'])]);
    if (!$stmt->fetch()) {
        $now = vox_now();
        $ends = gmdate('c', time() + 3650 * 86400);
        $insert = $pdo->prepare(
            'INSERT INTO users (id, email, password_hash, name, role, status, subscription_ends_at, created_at, updated_at)
             VALUES (?, ?, ?, ?, "admin", "active", ?, ?, ?)'
        );
        $insert->execute([
            vox_uuid(),
            strtolower($config['admin_email']),
            password_hash($config['admin_password'], PASSWORD_DEFAULT),
            $config['admin_name'],
            $ends,
            $now,
            $now,
        ]);
    }
}

function vox_public_user(array $row): array
{
    return [
        'id' => $row['id'],
        'email' => $row['email'],
        'name' => $row['name'],
        'role' => $row['role'],
        'status' => $row['status'],
        'subscription_ends_at' => $row['subscription_ends_at'],
        'admin_note' => $row['admin_note'] ?? '',
        'created_at' => $row['created_at'],
        'updated_at' => $row['updated_at'],
        'subscription_active' => vox_subscription_active($row),
        'days_remaining' => vox_days_remaining($row),
    ];
}

function vox_subscription_active(array $user): bool
{
    if (($user['role'] ?? '') === 'admin') {
        return true;
    }
    if (($user['status'] ?? '') !== 'active') {
        return false;
    }
    $ends = $user['subscription_ends_at'] ?? null;
    if (!$ends) {
        return false;
    }
    return strtotime($ends) >= time();
}

function vox_days_remaining(array $user): ?int
{
    $ends = $user['subscription_ends_at'] ?? null;
    if (!$ends) {
        return null;
    }
    $diff = (int) ceil((strtotime($ends) - time()) / 86400);
    return $diff;
}

function vox_bearer_token(): ?string
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (preg_match('/Bearer\s+(\S+)/i', $header, $m)) {
        return $m[1];
    }
    if (!empty($_SERVER['HTTP_X_AUTH_TOKEN'])) {
        return (string) $_SERVER['HTTP_X_AUTH_TOKEN'];
    }
    return null;
}

function vox_find_user_by_token(?string $token): ?array
{
    if (!$token) {
        return null;
    }
    $pdo = vox_db();
    $stmt = $pdo->prepare(
        'SELECT u.* FROM sessions s
         JOIN users u ON u.id = s.user_id
         WHERE s.token = ? AND s.expires_at > ? LIMIT 1'
    );
    $stmt->execute([$token, vox_now()]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function vox_require_user(bool $needActiveSub = true): array
{
    $user = vox_find_user_by_token(vox_bearer_token());
    if (!$user) {
        vox_json_response(['error' => 'Please log in'], 401);
    }
    if ($user['status'] === 'pending') {
        vox_json_response(['error' => 'Your account is waiting for admin approval', 'status' => 'pending'], 403);
    }
    if ($user['status'] === 'declined') {
        vox_json_response(['error' => 'Your account request was declined', 'status' => 'declined'], 403);
    }
    if ($user['status'] === 'restricted') {
        vox_json_response(['error' => 'Your account is restricted by admin', 'status' => 'restricted'], 403);
    }
    if ($needActiveSub && $user['role'] !== 'admin' && !vox_subscription_active($user)) {
        vox_json_response([
            'error' => 'Your monthly subscription has ended. Please renew.',
            'status' => 'expired',
            'subscription_ends_at' => $user['subscription_ends_at'],
        ], 402);
    }
    return $user;
}

function vox_require_admin(): array
{
    $user = vox_require_user(false);
    if (($user['role'] ?? '') !== 'admin') {
        vox_json_response(['error' => 'Admin only'], 403);
    }
    return $user;
}

function vox_create_session(string $userId): string
{
    $token = bin2hex(random_bytes(32));
    $pdo = vox_db();
    $stmt = $pdo->prepare(
        'INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)'
    );
    $stmt->execute([
        $token,
        $userId,
        gmdate('c', time() + 60 * 86400),
        vox_now(),
    ]);
    return $token;
}

function vox_send_mail(string $to, string $subject, string $body): bool
{
    $config = vox_config();
    $from = $config['mail_from'];
    $name = $config['mail_from_name'];
    $headers = [
        'MIME-Version: 1.0',
        'Content-type: text/plain; charset=utf-8',
        'From: ' . sprintf('%s <%s>', $name, $from),
    ];
    return @mail($to, $subject, $body, implode("\r\n", $headers));
}
