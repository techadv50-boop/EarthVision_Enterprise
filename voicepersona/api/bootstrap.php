<?php
declare(strict_types=1);

const VOX_ROOT = __DIR__ . '/..';
const VOX_DATA = VOX_ROOT . '/data';
const VOX_PERSONAS = VOX_DATA . '/personas';
const VOX_SAMPLES = VOX_DATA . '/samples';

function vox_ensure_dirs(): void
{
    foreach ([VOX_DATA, VOX_PERSONAS, VOX_SAMPLES] as $dir) {
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }
    }
}

function vox_json_response(mixed $data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization, X-Auth-Token');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function vox_read_json_body(): array
{
    $raw = file_get_contents('php://input') ?: '';
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        vox_json_response(['error' => 'Invalid JSON body'], 400);
    }
    return $data;
}

function vox_uuid(): string
{
    return bin2hex(random_bytes(16));
}

function vox_now(): string
{
    return gmdate('c');
}

function vox_persona_path(string $id): string
{
    return VOX_PERSONAS . '/' . $id . '.json';
}

function vox_load_persona(string $id): ?array
{
    $path = vox_persona_path($id);
    if (!is_file($path)) {
        return null;
    }
    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : null;
}

function vox_save_persona(array $persona): array
{
    vox_ensure_dirs();
    $persona['updated_at'] = vox_now();
    $path = vox_persona_path($persona['id']);
    file_put_contents(
        $path,
        json_encode($persona, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
    );
    return $persona;
}

function vox_list_personas(?string $ownerId = null): array
{
    vox_ensure_dirs();
    $out = [];
    foreach (glob(VOX_PERSONAS . '/*.json') ?: [] as $file) {
        $data = json_decode((string) file_get_contents($file), true);
        if (!is_array($data)) {
            continue;
        }
        if ($ownerId !== null && ($data['owner_id'] ?? '') !== $ownerId) {
            continue;
        }
        $out[] = $data;
    }
    usort($out, static fn($a, $b) => strcmp($a['name'] ?? '', $b['name'] ?? ''));
    return $out;
}

function vox_persona_owned(?array $persona, string $userId): bool
{
    return $persona !== null && ($persona['owner_id'] ?? '') === $userId;
}

function vox_default_traits(): array
{
    return [
        'language' => '',
        'accent' => '',
        'talking_style' => '',
        'vocabulary_notes' => '',
        'laugh_style' => '',
        'sadness_style' => '',
        'filler_words' => [],
        'catchphrases' => [],
        'moods_observed' => [],
        'extra' => [],
    ];
}

function vox_sample_dir(string $personaId): string
{
    $dir = VOX_SAMPLES . '/' . $personaId;
    if (!is_dir($dir)) {
        mkdir($dir, 0755, true);
    }
    return $dir;
}
