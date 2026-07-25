<?php
declare(strict_types=1);

require_once __DIR__ . '/eliza.php';

function vox_style_notes(array $persona, ?string $mood = null): array
{
    $traits = $persona['traits'] ?? vox_default_traits();
    $samples = $persona['samples'] ?? [];
    $notes = [];

    $accent = $traits['accent'] ?? '';
    if ($accent === '') {
        foreach ($samples as $s) {
            if (!empty($s['accent'])) {
                $accent = $s['accent'];
                break;
            }
        }
    }
    if ($accent !== '') {
        $notes[] = "Speak with a {$accent} accent flavor in word choice and rhythm.";
    }

    $style = $traits['talking_style'] ?? '';
    if ($style === '') {
        foreach ($samples as $s) {
            if (!empty($s['talking_style'])) {
                $style = $s['talking_style'];
                break;
            }
        }
    }
    if ($style !== '') {
        $notes[] = "Talking style: {$style}.";
    }

    if (!empty($traits['laugh_style'])) {
        $notes[] = "When amused, laugh like this: {$traits['laugh_style']}.";
    }
    if (!empty($traits['sadness_style'])) {
        $notes[] = "When sad, sound like this: {$traits['sadness_style']}.";
    }
    if (!empty($traits['vocabulary_notes'])) {
        $notes[] = 'Vocabulary: ' . $traits['vocabulary_notes'];
    }
    if (!empty($traits['filler_words'])) {
        $notes[] = 'Natural fillers: ' . implode(', ', $traits['filler_words']) . '.';
    }
    if (!empty($traits['catchphrases'])) {
        $notes[] = 'Occasionally use catchphrases: ' . implode('; ', $traits['catchphrases']) . '.';
    }

    $transcripts = [];
    foreach ($samples as $s) {
        if (!empty($s['transcript'])) {
            $transcripts[] = $s['transcript'];
        }
    }
    if ($transcripts) {
        $notes[] = 'Mirror phrasing from these samples: ' . implode(' | ', array_slice($transcripts, 0, 4));
    }

    if ($mood) {
        $notes[] = "Current reply mood target: {$mood}.";
    }

    if (!$notes) {
        $notes[] = 'Reply warmly and conversationally in first person as this persona.';
    }
    return $notes;
}

function vox_apply_style(string $text, array $persona, ?string $mood = null): string
{
    $traits = $persona['traits'] ?? vox_default_traits();
    $out = trim($text);

    $replacements = [
        '/\bPlease tell me more\b/i' => 'Tell me more, yeah?',
        '/\bVery interesting\b/i' => "That's interesting",
        '/\bI see\b/i' => 'Mm, I hear you',
        '/\bWhy do you ask\b/i' => 'Why you asking',
        '/\bHow does that make you feel\b/i' => "How's that sitting with you",
    ];
    foreach ($replacements as $pattern => $repl) {
        $out = preg_replace($pattern, $repl, $out) ?? $out;
    }

    $fillers = $traits['filler_words'] ?? [];
    if ($fillers && str_word_count($out) > 6) {
        $filler = $fillers[0];
        if (stripos($out, $filler) === false) {
            $out = ucfirst($filler) . ', ' . lcfirst($out);
        }
    }

    if ($mood === 'laughing') {
        $laugh = $traits['laugh_style'] ?: 'haha';
        if (stripos($out, $laugh) === false) {
            $out .= ' ' . $laugh;
        }
    } elseif ($mood === 'sad') {
        $cue = $traits['sadness_style'] ?: 'soft and quiet';
        if (!str_contains($out, '…') && !str_contains($out, '...')) {
            $out = rtrim($out, '.!') . '…';
        }
        $out .= " ({$cue})";
    }

    $phrases = $traits['catchphrases'] ?? [];
    if ($phrases && strlen($out) < 180 && (crc32($out) % 3 === 0)) {
        $phrase = $phrases[0];
        if (stripos($out, $phrase) === false) {
            $out .= ' ' . $phrase;
        }
    }

    $accent = strtolower((string) ($traits['accent'] ?? ''));
    if (str_contains($accent, 'southern') || str_contains($accent, 'texas')) {
        $out = preg_replace('/\byou all\b/i', "y'all", $out) ?? $out;
    }

    return $out;
}

function vox_generate_reply(array $persona, string $message, ?string $mood = null): array
{
    $styleNotes = vox_style_notes($persona, $mood);
    $engine = strtolower((string) ($persona['ai_engine'] ?? 'eliza'));
    $raw = vox_eliza_respond($message);
    $styled = vox_apply_style($raw, $persona, $mood);
    return [$styled, $engine === '' ? 'eliza' : $engine, $styleNotes];
}
