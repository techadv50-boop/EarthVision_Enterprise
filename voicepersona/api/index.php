<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/db.php';
require_once __DIR__ . '/persona_ai.php';

vox_ensure_dirs();
vox_db(); // ensure schema + admin seed

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization, X-Auth-Token');
    http_response_code(204);
    exit;
}

$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$uri = preg_replace('#^/api#', '', $uri) ?: '/';
$uri = rtrim($uri, '/') ?: '/';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

try {
    route_request($method, $uri);
} catch (Throwable $e) {
    vox_json_response(['error' => $e->getMessage()], 500);
}

function route_request(string $method, string $uri): void
{
    $config = vox_config();

    if ($method === 'GET' && $uri === '/health') {
        vox_json_response([
            'ok' => true,
            'service' => 'voxpersona',
            'hosting' => 'cpanel-php',
            'auth' => true,
            'subscription_price' => $config['subscription_price'],
            'subscription_currency' => $config['subscription_currency'],
            'llm_configured' => vox_llm_configured(),
        ]);
    }

    if ($method === 'GET' && $uri === '/public/config') {
        vox_json_response([
            'app_name' => $config['app_name'],
            'subscription_price' => $config['subscription_price'],
            'subscription_currency' => $config['subscription_currency'],
            'subscription_days' => $config['subscription_days'],
            'reminder_days_before' => $config['reminder_days_before'],
        ]);
    }

    // -------- Auth --------
    if ($method === 'POST' && $uri === '/auth/register') {
        $body = vox_read_json_body();
        $name = trim((string) ($body['name'] ?? ''));
        $email = strtolower(trim((string) ($body['email'] ?? '')));
        $password = (string) ($body['password'] ?? '');
        if ($name === '' || $email === '' || $password === '') {
            vox_json_response(['error' => 'Name, email and password are required'], 400);
        }
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            vox_json_response(['error' => 'Invalid email'], 400);
        }
        if (strlen($password) < 6) {
            vox_json_response(['error' => 'Password must be at least 6 characters'], 400);
        }
        $pdo = vox_db();
        $check = $pdo->prepare('SELECT id FROM users WHERE email = ?');
        $check->execute([$email]);
        if ($check->fetch()) {
            vox_json_response(['error' => 'An account with this email already exists'], 409);
        }
        $now = vox_now();
        $id = vox_uuid();
        $stmt = $pdo->prepare(
            'INSERT INTO users (id, email, password_hash, name, role, status, subscription_ends_at, created_at, updated_at)
             VALUES (?, ?, ?, ?, "user", "pending", NULL, ?, ?)'
        );
        $stmt->execute([$id, $email, password_hash($password, PASSWORD_DEFAULT), $name, $now, $now]);

        // Notify admin inbox via email (appears as account request)
        $adminEmail = $config['admin_email'];
        vox_send_mail(
            $adminEmail,
            'VoxPersona: new account request',
            "A new account request needs your review.\n\nName: {$name}\nEmail: {$email}\n\nLog in as admin to Allow, Decline, or Restrict.\n"
        );

        vox_json_response([
            'ok' => true,
            'message' => 'Account created. Waiting for admin approval before you can enter.',
            'status' => 'pending',
        ], 201);
    }

    if ($method === 'POST' && $uri === '/auth/login') {
        $body = vox_read_json_body();
        $email = strtolower(trim((string) ($body['email'] ?? '')));
        $password = (string) ($body['password'] ?? '');
        $pdo = vox_db();
        $stmt = $pdo->prepare('SELECT * FROM users WHERE email = ? LIMIT 1');
        $stmt->execute([$email]);
        $user = $stmt->fetch();
        if (!$user || !password_verify($password, $user['password_hash'])) {
            vox_json_response(['error' => 'Invalid email or password'], 401);
        }
        if ($user['status'] === 'pending') {
            vox_json_response([
                'error' => 'Your account request is waiting for admin approval.',
                'status' => 'pending',
            ], 403);
        }
        if ($user['status'] === 'declined') {
            vox_json_response([
                'error' => 'Your account request was declined by admin.',
                'status' => 'declined',
            ], 403);
        }
        if ($user['status'] === 'restricted') {
            vox_json_response([
                'error' => 'Your account is restricted. Contact admin.',
                'status' => 'restricted',
            ], 403);
        }
        if ($user['role'] !== 'admin' && !vox_subscription_active($user)) {
            // Allow login token so they can see renew screen, but mark expired
            $token = vox_create_session($user['id']);
            vox_json_response([
                'token' => $token,
                'user' => vox_public_user($user),
                'warning' => 'Subscription expired. Renew to continue using the studio.',
            ]);
        }
        $token = vox_create_session($user['id']);
        vox_json_response(['token' => $token, 'user' => vox_public_user($user)]);
    }

    if ($method === 'GET' && $uri === '/auth/me') {
        $user = vox_find_user_by_token(vox_bearer_token());
        if (!$user) {
            vox_json_response(['error' => 'Please log in'], 401);
        }
        vox_json_response([
            'user' => vox_public_user($user),
            'config' => [
                'subscription_price' => $config['subscription_price'],
                'subscription_currency' => $config['subscription_currency'],
                'subscription_days' => $config['subscription_days'],
            ],
        ]);
    }

    if ($method === 'POST' && $uri === '/auth/logout') {
        $token = vox_bearer_token();
        if ($token) {
            $pdo = vox_db();
            $pdo->prepare('DELETE FROM sessions WHERE token = ?')->execute([$token]);
        }
        vox_json_response(['ok' => true]);
    }

    if ($method === 'POST' && $uri === '/auth/renew-request') {
        $user = vox_require_user(false);
        if ($user['role'] === 'admin') {
            vox_json_response(['ok' => true, 'message' => 'Admin accounts do not need renewal']);
        }
        vox_send_mail(
            $config['admin_email'],
            'VoxPersona: renewal request',
            "User {$user['name']} ({$user['email']}) requested a subscription renewal.\nPlease extend their monthly plan from the admin panel.\n"
        );
        vox_send_mail(
            $user['email'],
            'VoxPersona: renewal request received',
            "Hello {$user['name']},\n\nWe received your renewal request for the monthly VoxPersona plan ({$config['subscription_currency']} {$config['subscription_price']}/month).\nAn admin will activate your next month shortly.\n"
        );
        vox_json_response(['ok' => true, 'message' => 'Renewal request sent to admin.']);
    }

    // -------- Admin --------
    if ($method === 'GET' && $uri === '/admin/users') {
        vox_require_admin();
        $pdo = vox_db();
        $rows = $pdo->query('SELECT * FROM users ORDER BY created_at DESC')->fetchAll();
        vox_json_response(array_map('vox_public_user', $rows));
    }

    if ($method === 'POST' && preg_match('#^/admin/users/([a-f0-9]+)/(allow|decline|restrict|renew)$#', $uri, $m)) {
        vox_require_admin();
        $pdo = vox_db();
        $stmt = $pdo->prepare('SELECT * FROM users WHERE id = ? LIMIT 1');
        $stmt->execute([$m[1]]);
        $target = $stmt->fetch();
        if (!$target) {
            vox_json_response(['error' => 'User not found'], 404);
        }
        if ($target['role'] === 'admin') {
            vox_json_response(['error' => 'Cannot change the admin account this way'], 400);
        }

        $action = $m[2];
        $body = $method === 'POST' ? vox_read_json_body() : [];
        $note = trim((string) ($body['note'] ?? ''));
        $now = vox_now();
        $days = (int) $config['subscription_days'];

        if ($action === 'allow') {
            $ends = gmdate('c', time() + $days * 86400);
            $pdo->prepare(
                'UPDATE users SET status = "active", subscription_ends_at = ?, admin_note = ?, updated_at = ? WHERE id = ?'
            )->execute([$ends, $note, $now, $target['id']]);
            vox_send_mail(
                $target['email'],
                'VoxPersona: account approved',
                "Hello {$target['name']},\n\nYour account was approved. Your monthly subscription is active until {$ends}.\nPrice: {$config['subscription_currency']} {$config['subscription_price']} / month.\n\nYou can now log in and use VoxPersona.\n"
            );
        } elseif ($action === 'decline') {
            $pdo->prepare(
                'UPDATE users SET status = "declined", subscription_ends_at = NULL, admin_note = ?, updated_at = ? WHERE id = ?'
            )->execute([$note, $now, $target['id']]);
            vox_send_mail(
                $target['email'],
                'VoxPersona: account declined',
                "Hello {$target['name']},\n\nYour account request was declined by the administrator.\n"
            );
        } elseif ($action === 'restrict') {
            $pdo->prepare(
                'UPDATE users SET status = "restricted", admin_note = ?, updated_at = ? WHERE id = ?'
            )->execute([$note, $now, $target['id']]);
            // Drop sessions so they cannot keep using the app
            $pdo->prepare('DELETE FROM sessions WHERE user_id = ?')->execute([$target['id']]);
            vox_send_mail(
                $target['email'],
                'VoxPersona: account restricted',
                "Hello {$target['name']},\n\nYour account has been restricted by the administrator. Contact support if you need help.\n"
            );
        } elseif ($action === 'renew') {
            $base = time();
            if (!empty($target['subscription_ends_at']) && strtotime($target['subscription_ends_at']) > time()) {
                $base = strtotime($target['subscription_ends_at']);
            }
            $ends = gmdate('c', $base + $days * 86400);
            $pdo->prepare(
                'UPDATE users SET status = "active", subscription_ends_at = ?, admin_note = ?, updated_at = ?, last_reminder_sent_at = NULL WHERE id = ?'
            )->execute([$ends, $note, $now, $target['id']]);
            vox_send_mail(
                $target['email'],
                'VoxPersona: subscription renewed',
                "Hello {$target['name']},\n\nYour monthly subscription was renewed until {$ends}.\nThank you for staying with VoxPersona.\n"
            );
        }

        $stmt->execute([$m[1]]);
        $fresh = $stmt->fetch();
        vox_json_response(['user' => vox_public_user($fresh)]);
    }

    // -------- Cron: subscription reminders --------
    if ($method === 'GET' && $uri === '/cron/reminders') {
        $key = $_GET['key'] ?? '';
        if (!hash_equals((string) $config['cron_key'], (string) $key)) {
            vox_json_response(['error' => 'Invalid cron key'], 403);
        }
        $days = (int) $config['reminder_days_before'];
        $pdo = vox_db();
        $rows = $pdo->query(
            'SELECT * FROM users WHERE role = "user" AND status = "active" AND subscription_ends_at IS NOT NULL'
        )->fetchAll();
        $sent = 0;
        $checked = 0;
        foreach ($rows as $user) {
            $checked++;
            $remaining = vox_days_remaining($user);
            if ($remaining === null || $remaining > $days || $remaining < 0) {
                continue;
            }
            // Avoid spamming more than once per 3 days
            if (!empty($user['last_reminder_sent_at']) && strtotime($user['last_reminder_sent_at']) > time() - 3 * 86400) {
                continue;
            }
            $ends = $user['subscription_ends_at'];
            $ok = vox_send_mail(
                $user['email'],
                'VoxPersona: renew your monthly subscription',
                "Hello {$user['name']},\n\nYour VoxPersona subscription is near its end (expires {$ends}).\nDays remaining: {$remaining}.\n\nPlan: {$config['subscription_currency']} {$config['subscription_price']} / month.\nPlease log in and request renewal, or contact the administrator.\n\n— VoxPersona\n"
            );
            if ($ok) {
                $pdo->prepare('UPDATE users SET last_reminder_sent_at = ? WHERE id = ?')
                    ->execute([vox_now(), $user['id']]);
                $sent++;
            }
        }
        vox_json_response(['ok' => true, 'checked' => $checked, 'reminders_sent' => $sent]);
    }

    // -------- App data (auth + active subscription required) --------
    if ($method === 'GET' && $uri === '/engines') {
        vox_require_user(true);
        $engines = [
            [
                'id' => 'discussion',
                'name' => vox_llm_configured() ? 'Discussion AI (LLM)' : 'Discussion AI',
                'description' => vox_llm_configured()
                    ? 'OpenAI-compatible model for natural conversation and style analysis.'
                    : 'Built-in discussion engine. Add llm_api_key in config.php for full LLM chat (OpenAI/Groq/etc).',
            ],
            [
                'id' => 'eliza',
                'name' => 'Eliza',
                'description' => 'Classic pattern chatbot fallback.',
            ],
        ];
        vox_json_response([
            'engines' => $engines,
            'llm_configured' => vox_llm_configured(),
        ]);
    }

    if ($method === 'GET' && $uri === '/moods') {
        vox_require_user(true);
        vox_json_response([
            'moods' => [
                'neutral', 'happy', 'sad', 'laughing', 'angry', 'excited',
                'calm', 'anxious', 'affectionate', 'sarcastic',
            ],
        ]);
    }

    if ($method === 'GET' && $uri === '/personas') {
        $user = vox_require_user(true);
        vox_json_response(vox_list_personas($user['id']));
    }

    if ($method === 'POST' && $uri === '/personas') {
        $user = vox_require_user(true);
        $body = vox_read_json_body();
        $name = trim((string) ($body['name'] ?? ''));
        if ($name === '') {
            vox_json_response(['error' => 'Name is required'], 400);
        }
        $persona = [
            'id' => vox_uuid(),
            'owner_id' => $user['id'],
            'name' => $name,
            'description' => trim((string) ($body['description'] ?? '')),
            'traits' => array_merge(vox_default_traits(), is_array($body['traits'] ?? null) ? $body['traits'] : []),
            'samples' => [],
            'ai_engine' => $body['ai_engine'] ?? 'discussion',
            'voice_clone_id' => $body['voice_clone_id'] ?? null,
            'created_at' => vox_now(),
            'updated_at' => vox_now(),
        ];
        vox_json_response(vox_save_persona($persona), 201);
    }

    if (preg_match('#^/personas/([a-f0-9]+)$#', $uri, $m)) {
        $user = vox_require_user(true);
        $persona = vox_load_persona($m[1]);
        if (!vox_persona_owned($persona, $user['id'])) {
            vox_json_response(['error' => 'Persona not found'], 404);
        }
        if ($method === 'GET') {
            vox_json_response($persona);
        }
        if ($method === 'PATCH') {
            $body = vox_read_json_body();
            foreach (['name', 'description', 'ai_engine', 'voice_clone_id'] as $key) {
                if (array_key_exists($key, $body)) {
                    $persona[$key] = $body[$key];
                }
            }
            if (isset($body['traits']) && is_array($body['traits'])) {
                $persona['traits'] = array_merge(vox_default_traits(), $body['traits']);
            }
            vox_json_response(vox_save_persona($persona));
        }
        if ($method === 'DELETE') {
            @unlink(vox_persona_path($m[1]));
            $dir = VOX_SAMPLES . '/' . $m[1];
            if (is_dir($dir)) {
                foreach (glob($dir . '/*') ?: [] as $file) {
                    @unlink($file);
                }
                @rmdir($dir);
            }
            vox_json_response(['deleted' => true]);
        }
    }

    if ($method === 'POST' && preg_match('#^/personas/([a-f0-9]+)/samples$#', $uri, $m)) {
        $user = vox_require_user(true);
        $persona = vox_load_persona($m[1]);
        if (!vox_persona_owned($persona, $user['id'])) {
            vox_json_response(['error' => 'Persona not found'], 404);
        }
        if (empty($_FILES['file']['tmp_name'])) {
            vox_json_response(['error' => 'Audio file is required'], 400);
        }
        $meta = json_decode((string) ($_POST['meta'] ?? '{}'), true);
        if (!is_array($meta)) {
            vox_json_response(['error' => 'Invalid sample meta'], 400);
        }

        $original = (string) ($_FILES['file']['name'] ?? 'sample.webm');
        $ext = pathinfo($original, PATHINFO_EXTENSION) ?: 'webm';
        $filename = vox_uuid() . '.' . preg_replace('/[^a-zA-Z0-9]/', '', $ext);
        $dest = vox_sample_dir($m[1]) . '/' . $filename;
        if (!move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
            vox_json_response(['error' => 'Failed to store audio'], 500);
        }

        $transcript = trim((string) ($meta['transcript'] ?? ''));
        $auto = !empty($meta['auto_analyze']) || $transcript !== '';
        $analysis = $auto && $transcript !== ''
            ? vox_analyze_speech($transcript, $persona['traits'] ?? [])
            : [];

        $sample = [
            'id' => vox_uuid(),
            'filename' => $filename,
            'kind' => $meta['kind'] ?? 'speech',
            'transcript' => $transcript,
            'language' => trim((string) ($meta['language'] ?? ($analysis['language'] ?? ''))),
            'accent' => trim((string) ($meta['accent'] ?? ($analysis['accent'] ?? ''))),
            'talking_style' => trim((string) ($meta['talking_style'] ?? ($analysis['talking_style'] ?? ''))),
            'moods' => array_values(array_filter(
                (array) ($meta['moods'] ?? ($analysis['moods'] ?? ['neutral']))
            )),
            'notes' => trim((string) ($meta['notes'] ?? ($analysis['notes'] ?? ''))),
            'duration_ms' => isset($meta['duration_ms']) ? (int) $meta['duration_ms'] : null,
            'source' => $meta['source'] ?? 'upload',
            'analysis' => $analysis,
            'created_at' => vox_now(),
        ];
        $persona['samples'][] = $sample;

        if ($analysis) {
            $persona['traits'] = vox_merge_traits($persona['traits'] ?? [], $analysis);
        } else {
            if ($sample['accent'] !== '' && empty($persona['traits']['accent'])) {
                $persona['traits']['accent'] = $sample['accent'];
            }
            if ($sample['talking_style'] !== '' && empty($persona['traits']['talking_style'])) {
                $persona['traits']['talking_style'] = $sample['talking_style'];
            }
            foreach ($sample['moods'] as $mood) {
                if (!in_array($mood, $persona['traits']['moods_observed'], true)) {
                    $persona['traits']['moods_observed'][] = $mood;
                }
            }
        }

        $saved = vox_save_persona($persona);
        vox_json_response([
            'sample' => $sample,
            'persona' => $saved,
            'auto_traits' => [
                'language' => $saved['traits']['language'] ?? '',
                'accent' => $saved['traits']['accent'] ?? '',
                'talking_style' => $saved['traits']['talking_style'] ?? '',
                'laugh_style' => $saved['traits']['laugh_style'] ?? '',
                'sadness_style' => $saved['traits']['sadness_style'] ?? '',
            ],
        ], 201);
    }

    if ($method === 'GET' && preg_match('#^/personas/([a-f0-9]+)/samples/([^/]+)/audio$#', $uri, $m)) {
        // <audio src> cannot send Authorization headers — allow ?token=
        $token = vox_bearer_token() ?: ($_GET['token'] ?? null);
        $user = vox_find_user_by_token(is_string($token) ? $token : null);
        if (!$user || $user['status'] !== 'active' || ($user['role'] !== 'admin' && !vox_subscription_active($user))) {
            vox_json_response(['error' => 'Please log in'], 401);
        }
        $persona = vox_load_persona($m[1]);
        if (!vox_persona_owned($persona, $user['id'])) {
            vox_json_response(['error' => 'Audio not found'], 404);
        }
        $path = vox_sample_dir($m[1]) . '/' . basename($m[2]);
        if (!is_file($path)) {
            vox_json_response(['error' => 'Audio not found'], 404);
        }
        $mime = mime_content_type($path) ?: 'application/octet-stream';
        header('Access-Control-Allow-Origin: *');
        header('Content-Type: ' . $mime);
        header('Content-Length: ' . (string) filesize($path));
        readfile($path);
        exit;
    }

    if ($method === 'DELETE' && preg_match('#^/personas/([a-f0-9]+)/samples/([a-f0-9]+)$#', $uri, $m)) {
        $user = vox_require_user(true);
        $persona = vox_load_persona($m[1]);
        if (!vox_persona_owned($persona, $user['id'])) {
            vox_json_response(['error' => 'Persona not found'], 404);
        }
        $found = null;
        $kept = [];
        foreach ($persona['samples'] as $sample) {
            if (($sample['id'] ?? '') === $m[2]) {
                $found = $sample;
                continue;
            }
            $kept[] = $sample;
        }
        if (!$found) {
            vox_json_response(['error' => 'Sample not found'], 404);
        }
        @unlink(vox_sample_dir($m[1]) . '/' . $found['filename']);
        $persona['samples'] = $kept;
        vox_json_response(vox_save_persona($persona));
    }

    if ($method === 'POST' && preg_match('#^/personas/([a-f0-9]+)/chat$#', $uri, $m)) {
        $user = vox_require_user(true);
        $persona = vox_load_persona($m[1]);
        if (!vox_persona_owned($persona, $user['id'])) {
            vox_json_response(['error' => 'Persona not found'], 404);
        }
        $body = vox_read_json_body();
        $message = trim((string) ($body['message'] ?? ''));
        if ($message === '') {
            vox_json_response(['error' => 'Message is required'], 400);
        }
        $mood = isset($body['mood']) ? (string) $body['mood'] : null;
        $history = is_array($body['history'] ?? null) ? $body['history'] : [];
        [$reply, $engine, $styleNotes] = vox_generate_reply($persona, $message, $mood, $history);
        vox_json_response([
            'reply' => $reply,
            'engine' => $engine,
            'style_notes' => $styleNotes,
            'audio_url' => null,
            'llm_configured' => vox_llm_configured(),
        ]);
    }

    vox_json_response(['error' => 'Not found', 'path' => $uri], 404);
}
