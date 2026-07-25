<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/persona_ai.php';

vox_ensure_dirs();

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
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
    if ($method === 'GET' && $uri === '/health') {
        vox_json_response(['ok' => true, 'service' => 'voxpersona', 'hosting' => 'cpanel-php', 'ai_default' => 'eliza']);
    }

    if ($method === 'GET' && $uri === '/engines') {
        vox_json_response([
            'engines' => [
                [
                    'id' => 'eliza',
                    'name' => 'Eliza',
                    'description' => 'Built-in conversational agent for cPanel. No external API required.',
                ],
            ],
        ]);
    }

    if ($method === 'GET' && $uri === '/moods') {
        vox_json_response([
            'moods' => [
                'neutral', 'happy', 'sad', 'laughing', 'angry', 'excited',
                'calm', 'anxious', 'affectionate', 'sarcastic',
            ],
        ]);
    }

    if ($method === 'GET' && $uri === '/personas') {
        vox_json_response(vox_list_personas());
    }

    if ($method === 'POST' && $uri === '/personas') {
        $body = vox_read_json_body();
        $name = trim((string) ($body['name'] ?? ''));
        if ($name === '') {
            vox_json_response(['error' => 'Name is required'], 400);
        }
        $persona = [
            'id' => vox_uuid(),
            'name' => $name,
            'description' => trim((string) ($body['description'] ?? '')),
            'traits' => array_merge(vox_default_traits(), is_array($body['traits'] ?? null) ? $body['traits'] : []),
            'samples' => [],
            'ai_engine' => $body['ai_engine'] ?? 'eliza',
            'voice_clone_id' => $body['voice_clone_id'] ?? null,
            'created_at' => vox_now(),
            'updated_at' => vox_now(),
        ];
        vox_json_response(vox_save_persona($persona), 201);
    }

    if (preg_match('#^/personas/([a-f0-9]+)$#', $uri, $m)) {
        $persona = vox_load_persona($m[1]);
        if (!$persona) {
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
        $persona = vox_load_persona($m[1]);
        if (!$persona) {
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

        $sample = [
            'id' => vox_uuid(),
            'filename' => $filename,
            'kind' => $meta['kind'] ?? 'speech',
            'transcript' => trim((string) ($meta['transcript'] ?? '')),
            'accent' => trim((string) ($meta['accent'] ?? '')),
            'talking_style' => trim((string) ($meta['talking_style'] ?? '')),
            'moods' => array_values(array_filter((array) ($meta['moods'] ?? []))),
            'notes' => trim((string) ($meta['notes'] ?? '')),
            'duration_ms' => isset($meta['duration_ms']) ? (int) $meta['duration_ms'] : null,
            'source' => $meta['source'] ?? 'upload',
            'created_at' => vox_now(),
        ];
        $persona['samples'][] = $sample;

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
        if (($sample['kind'] ?? '') === 'laughing' && $sample['notes'] !== '' && empty($persona['traits']['laugh_style'])) {
            $persona['traits']['laugh_style'] = $sample['notes'];
        }
        if (($sample['kind'] ?? '') === 'sadness' && $sample['notes'] !== '' && empty($persona['traits']['sadness_style'])) {
            $persona['traits']['sadness_style'] = $sample['notes'];
        }

        vox_save_persona($persona);
        vox_json_response($sample, 201);
    }

    if ($method === 'GET' && preg_match('#^/personas/([a-f0-9]+)/samples/([^/]+)/audio$#', $uri, $m)) {
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
        $persona = vox_load_persona($m[1]);
        if (!$persona) {
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
        $persona = vox_load_persona($m[1]);
        if (!$persona) {
            vox_json_response(['error' => 'Persona not found'], 404);
        }
        $body = vox_read_json_body();
        $message = trim((string) ($body['message'] ?? ''));
        if ($message === '') {
            vox_json_response(['error' => 'Message is required'], 400);
        }
        $mood = isset($body['mood']) ? (string) $body['mood'] : null;
        [$reply, $engine, $styleNotes] = vox_generate_reply($persona, $message, $mood);
        vox_json_response([
            'reply' => $reply,
            'engine' => $engine,
            'style_notes' => $styleNotes,
            'audio_url' => null,
        ]);
    }

    vox_json_response(['error' => 'Not found', 'path' => $uri], 404);
}
