<?php
declare(strict_types=1);

require_once __DIR__ . '/eliza.php';
require_once __DIR__ . '/llm.php';

function vox_style_notes(array $persona, ?string $mood = null): array
{
    $traits = $persona['traits'] ?? vox_default_traits();
    $samples = $persona['samples'] ?? [];
    $notes = [];

    if (!empty($traits['language'])) {
        $notes[] = "Preferred language(s): {$traits['language']}.";
    }

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
        $notes[] = 'Mirror phrasing from these samples: ' . implode(' | ', array_slice($transcripts, 0, 6));
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

    $fillers = $traits['filler_words'] ?? [];
    if ($fillers && str_word_count($out) > 6) {
        $filler = $fillers[0];
        if (stripos($out, $filler) === false) {
            $out = ucfirst($filler) . ', ' . lcfirst($out);
        }
    }

    if ($mood === 'laughing') {
        $laugh = $traits['laugh_style'] ?: 'haha';
        if (stripos($out, (string) $laugh) === false) {
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

    return $out;
}

/**
 * Built-in discussion partner (used when no LLM key is set).
 * Far more conversational than classic Eliza — keeps a real back-and-forth.
 */
function vox_discussion_fallback(string $message, array $persona, array $history = []): string
{
    $name = $persona['name'] ?? 'Friend';
    $traits = $persona['traits'] ?? vox_default_traits();
    $msg = trim($message);
    $lower = mb_strtolower($msg);

    $samples = [];
    foreach ($persona['samples'] ?? [] as $s) {
        if (!empty($s['transcript'])) {
            $samples[] = $s['transcript'];
        }
    }

    if ($msg === '') {
        return "I'm here with you. Tell me anything that's on your mind.";
    }

    if (preg_match('/\b(hi|hello|salam|assalam|hey)\b/i', $msg)) {
        $lang = $traits['language'] ?? '';
        if (stripos($lang, 'punjabi') !== false || stripos($lang, 'urdu') !== false) {
            return "Wa-alaikum. It's good to talk. How are you feeling today?";
        }
        return "Hello — I'm glad we're talking. How has your day been?";
    }

    if (preg_match('/\b(how are you|ki haal|kaisa|kese ho)\b/i', $msg)) {
        return "I'm doing alright, thank you for asking. More importantly — how are you, really?";
    }

    if (preg_match('/\b(family|son|daughter|beta|bibi|wife|husband|children)\b/i', $msg)) {
        return "Family stays close to the heart. Tell me more about them — what makes you smile when you think of them?";
    }

    if (preg_match('/\b(remember|memory|old days|childhood|young)\b/i', $msg)) {
        return "Those memories matter. What moment from those days do you still see clearly?";
    }

    if (preg_match('/\b(sad|alone|miss|dukh|tired|pain)\b/i', $msg)) {
        $soft = $traits['sadness_style'] ?: 'softly';
        return "I hear you. It sounds heavy. I'm here with you — want to tell me what hurts most right now? ({$soft})";
    }

    if (preg_match('/\b(haha|funny|laugh|joke)\b/i', $msg)) {
        $laugh = $traits['laugh_style'] ?: 'haha';
        return "That made me smile too {$laugh}. What else has been making you laugh lately?";
    }

    if (str_ends_with(rtrim($msg, '.!'), '?')) {
        // Answer then continue the discussion
        $echo = vox_eliza_respond($msg);
        return $echo . ' And what do you think about it yourself?';
    }

    // Continue discussion using captured phrasing if available
    if ($samples) {
        $hint = $samples[array_rand($samples)];
        return "I understand. When you say things like \"{$hint}\", I can hear your way of speaking. "
            . "Please go on — what happened next?";
    }

    $openers = [
        "That sounds important. Tell me more.",
        "I'm listening. What else comes with that?",
        "Go on — I want to understand it the way you see it.",
        "Thank you for sharing that. How did it make you feel?",
        "I hear you, {$name}'s friend. What would you like to talk about next?",
    ];
    return $openers[array_rand($openers)];
}

function vox_generate_reply(
    array $persona,
    string $message,
    ?string $mood = null,
    array $history = []
): array {
    $styleNotes = vox_style_notes($persona, $mood);
    $enginePref = strtolower((string) ($persona['ai_engine'] ?? 'discussion'));

    // Prefer real LLM discussion whenever configured (unless forced to eliza).
    if ($enginePref !== 'eliza' && vox_llm_configured()) {
        $system = "You are having a natural, warm discussion. "
            . "When role is 'persona', embody {$persona['name']} using their captured voice traits. "
            . "When helping capture speech, be a gentle conversational partner. "
            . "Stay in character. Keep replies short to medium. Match their language when possible.\n"
            . "Style rules:\n- " . implode("\n- ", $styleNotes);
        if (!empty($persona['description'])) {
            $system .= "\nDescription: {$persona['description']}";
        }

        $messages = [['role' => 'system', 'content' => $system]];
        foreach (array_slice($history, -12) as $item) {
            $role = (($item['role'] ?? '') === 'assistant') ? 'assistant' : 'user';
            $messages[] = ['role' => $role, 'content' => (string) ($item['content'] ?? '')];
        }
        $messages[] = ['role' => 'user', 'content' => $message];

        $llm = vox_llm_chat($messages, 0.8);
        if ($llm) {
            return [$llm, 'llm', $styleNotes];
        }
    }

    if ($enginePref === 'eliza') {
        $raw = vox_eliza_respond($message);
        return [vox_apply_style($raw, $persona, $mood), 'eliza', $styleNotes];
    }

    $raw = vox_discussion_fallback($message, $persona, $history);
    return [vox_apply_style($raw, $persona, $mood), 'discussion', $styleNotes];
}
