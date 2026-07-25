<?php
declare(strict_types=1);

require_once __DIR__ . '/db.php';

function vox_llm_configured(): bool
{
    $config = vox_config();
    return trim((string) ($config['llm_api_key'] ?? '')) !== '';
}

function vox_llm_chat(array $messages, float $temperature = 0.7): ?string
{
    $config = vox_config();
    $apiKey = trim((string) ($config['llm_api_key'] ?? ''));
    if ($apiKey === '') {
        return null;
    }

    $base = rtrim((string) ($config['llm_base_url'] ?? 'https://api.openai.com/v1'), '/');
    $model = (string) ($config['llm_model'] ?? 'gpt-4o-mini');
    $payload = json_encode([
        'model' => $model,
        'messages' => $messages,
        'temperature' => $temperature,
    ], JSON_UNESCAPED_UNICODE);

    $ch = curl_init($base . '/chat/completions');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
            'Authorization: Bearer ' . $apiKey,
        ],
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
    ]);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($raw === false || $code >= 400) {
        return null;
    }
    $data = json_decode($raw, true);
    $text = $data['choices'][0]['message']['content'] ?? null;
    return is_string($text) ? trim($text) : null;
}

/**
 * Analyze a spoken transcript into language/accent/style traits.
 * Uses LLM when configured; otherwise local heuristics.
 */
function vox_analyze_speech(string $transcript, array $existingTraits = []): array
{
    $transcript = trim($transcript);
    $base = [
        'language' => '',
        'accent' => '',
        'talking_style' => '',
        'laugh_style' => '',
        'sadness_style' => '',
        'vocabulary_notes' => '',
        'filler_words' => [],
        'catchphrases' => [],
        'moods' => ['neutral'],
        'notes' => '',
    ];

    if ($transcript === '') {
        return $base;
    }

    if (vox_llm_configured()) {
        $prompt = "Analyze this spoken utterance from an elderly person. "
            . "Return ONLY compact JSON with keys: language, accent, talking_style, laugh_style, "
            . "sadness_style, vocabulary_notes, filler_words (array), catchphrases (array), "
            . "moods (array from: neutral,happy,sad,laughing,angry,excited,calm,anxious,affectionate,sarcastic), notes.\n"
            . "Detect real language (English, Punjabi, Urdu, Hindi, mixed, etc.), accent cues, "
            . "and speaking manner. If uncertain, give best guess from evidence.\n\n"
            . "Utterance:\n\"\"\"{$transcript}\"\"\"";

        $reply = vox_llm_chat([
            ['role' => 'system', 'content' => 'You extract speech style traits. Reply with JSON only.'],
            ['role' => 'user', 'content' => $prompt],
        ], 0.2);

        if ($reply) {
            if (preg_match('/\{.*\}/s', $reply, $m)) {
                $parsed = json_decode($m[0], true);
                if (is_array($parsed)) {
                    return array_merge($base, array_intersect_key($parsed, $base));
                }
            }
        }
    }

    return array_merge($base, vox_heuristic_analyze($transcript));
}

function vox_heuristic_analyze(string $transcript): array
{
    $lower = mb_strtolower($transcript);
    $language = 'English';
    $accent = 'neutral English';

    $hasArabicScript = (bool) preg_match('/[\x{0600}-\x{06FF}]/u', $transcript);
    $hasGurmukhi = (bool) preg_match('/[\x{0A00}-\x{0A7F}]/u', $transcript);
    $hasDevanagari = (bool) preg_match('/[\x{0900}-\x{097F}]/u', $transcript);

    $punjabiHints = ['ki haal', 'ki hale', 'oye', 'yaar', 'veere', 'putt', 'bibi', 'ji', 'haanji', 'theek', 'acha', 'sun', 'menu', 'tusi', 'ki'];
    $urduHints = ['allah', 'beta', 'bibi', 'janab', 'haan', 'theek hai', 'acha', 'khuda', 'hafiz', 'shukriya'];
    $hindiHints = ['namaste', 'kya', 'haan', 'bahut', 'accha', 'beta'];

    $punjabiScore = 0;
    foreach ($punjabiHints as $w) {
        if (str_contains($lower, $w)) {
            $punjabiScore++;
        }
    }
    $urduScore = 0;
    foreach ($urduHints as $w) {
        if (str_contains($lower, $w)) {
            $urduScore++;
        }
    }
    $hindiScore = 0;
    foreach ($hindiHints as $w) {
        if (str_contains($lower, $w)) {
            $hindiScore++;
        }
    }

    if ($hasGurmukhi || $punjabiScore >= 2) {
        $language = $hasGurmukhi ? 'Punjabi' : 'Punjabi-English mix';
        $accent = 'Punjabi-influenced';
    } elseif ($hasArabicScript || $urduScore >= 2) {
        $language = $hasArabicScript ? 'Urdu' : 'Urdu-English mix';
        $accent = 'Urdu/Pakistani-influenced';
    } elseif ($hasDevanagari || $hindiScore >= 2) {
        $language = $hasDevanagari ? 'Hindi' : 'Hindi-English mix';
        $accent = 'Hindi-influenced';
    } elseif (preg_match('/\b(y\'?all|gonna|wanna|ain\'t)\b/', $lower)) {
        $accent = 'informal American English';
    }

    $words = preg_split('/\s+/', trim($transcript)) ?: [];
    $avgLen = count($words) ? strlen($transcript) / max(count($words), 1) : 0;
    $sentences = preg_split('/[.!?]+/', $transcript) ?: [];
    $styleBits = [];
    if (count($words) <= 6) {
        $styleBits[] = 'short phrases';
    } elseif (count($words) >= 20) {
        $styleBits[] = 'storytelling / longer turns';
    } else {
        $styleBits[] = 'conversational';
    }
    if (str_contains($transcript, '?')) {
        $styleBits[] = 'asks questions';
    }
    if ($avgLen < 4.2) {
        $styleBits[] = 'simple vocabulary';
    }
    if (count($sentences) <= 1 && count($words) > 12) {
        $styleBits[] = 'flowing speech';
    }

    $moods = ['neutral'];
    $laugh = '';
    $sad = '';
    if (preg_match('/\b(haha|ha ha|hehe|lol|teehee|chuckle)\b/i', $transcript) || str_contains($lower, '😂')) {
        $moods = ['laughing', 'happy'];
        $laugh = preg_match('/(ha(\s*ha)+|hehe+)/i', $transcript, $m)
            ? strtolower($m[0])
            : 'light laugh (haha)';
    }
    if (preg_match('/\b(sad|cry|miss|alone|tired|pain|dukh|rona)\b/i', $transcript)) {
        $moods[] = 'sad';
        $sad = 'softer, quieter tone when emotional';
    }
    if (preg_match('/\b(love|beta|son|daughter|jaan)\b/i', $transcript)) {
        $moods[] = 'affectionate';
    }

    $fillers = [];
    foreach (['you know', 'um', 'uh', 'matlab', 'yaar', 'acha', 'haan', 'ji', 'like'] as $f) {
        if (str_contains($lower, $f)) {
            $fillers[] = $f;
        }
    }

    return [
        'language' => $language,
        'accent' => $accent,
        'talking_style' => implode(', ', $styleBits),
        'laugh_style' => $laugh,
        'sadness_style' => $sad,
        'vocabulary_notes' => 'Auto-captured from live speech',
        'filler_words' => $fillers,
        'catchphrases' => [],
        'moods' => array_values(array_unique($moods)),
        'notes' => 'Auto-analyzed from conversation audio/transcript',
    ];
}

function vox_merge_traits(array $traits, array $analysis): array
{
    $traits = array_merge(vox_default_traits(), $traits);

    foreach (['language', 'accent', 'talking_style', 'laugh_style', 'sadness_style', 'vocabulary_notes'] as $key) {
        if (!empty($analysis[$key]) && empty($traits[$key])) {
            $traits[$key] = $analysis[$key];
        } elseif (!empty($analysis[$key]) && !empty($traits[$key]) && is_string($traits[$key])) {
            // Enrich lightly if new signal differs
            if (stripos($traits[$key], (string) $analysis[$key]) === false && in_array($key, ['talking_style', 'vocabulary_notes'], true)) {
                $traits[$key] = trim($traits[$key] . '; ' . $analysis[$key], " ;");
            }
        }
    }

    foreach (['filler_words', 'catchphrases'] as $listKey) {
        $incoming = $analysis[$listKey] ?? [];
        if (!is_array($incoming)) {
            continue;
        }
        foreach ($incoming as $item) {
            $item = trim((string) $item);
            if ($item !== '' && !in_array($item, $traits[$listKey], true)) {
                $traits[$listKey][] = $item;
            }
        }
    }

    $moods = $analysis['moods'] ?? [];
    if (is_array($moods)) {
        foreach ($moods as $mood) {
            if (!in_array($mood, $traits['moods_observed'], true)) {
                $traits['moods_observed'][] = $mood;
            }
        }
    }

    return $traits;
}
