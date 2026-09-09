<?php
declare(strict_types=1);

function vox_eliza_reflect(string $fragment): string
{
    $map = [
        'am' => 'are', 'was' => 'were', 'i' => 'you', "i'd" => 'you would',
        "i've" => 'you have', "i'll" => 'you will', 'my' => 'your', 'are' => 'am',
        "you've" => 'I have', "you'll" => 'I will', 'your' => 'my', 'yours' => 'mine',
        'you' => 'me', 'me' => 'you',
    ];
    $words = preg_split('/\s+/', strtolower(trim($fragment))) ?: [];
    $out = [];
    foreach ($words as $word) {
        $out[] = $map[$word] ?? $word;
    }
    return implode(' ', $out);
}

function vox_eliza_respond(string $input): string
{
    $text = trim($input);
    if ($text === '') {
        return "I'm listening. Tell me what's on your mind.";
    }

    $patterns = [
        ['/i need (.*)/i', ["Why do you need {0}?", "Would it really help you to get {0}?", "Are you sure you need {0}?"]],
        ['/i am (.*)/i', ["How long have you been {0}?", "How do you feel about being {0}?", "Did you come here because you are {0}?"]],
        ["/i'?m (.*)/i", ["How does being {0} make you feel?", "Do you enjoy being {0}?"]],
        ['/i feel (.*)/i', ["Tell me more about such feelings.", "Do you often feel {0}?", "When do you usually feel {0}?"]],
        ['/i think (.*)/i', ["Do you doubt {0}?", "Do you really think so?", "But you're not sure {0}?"]],
        ['/i want (.*)/i', ["What would it mean if you got {0}?", "Why do you want {0}?", "What would you do if you got {0}?"]],
        ['/i have (.*)/i', ["Why do you tell me that you've {0}?", "Have you really {0}?"]],
        ['/i can\'?t (.*)/i', ["How do you know you can't {0}?", "What would it take for you to {0}?"]],
        ['/my (.*)/i', ["I see, your {0}.", "Why do you say that your {0}?", "When your {0}, how do you feel?"]],
        ['/because (.*)/i', ["Is that the real reason?", "What other reasons come to mind?"]],
        ['/hello(.*)/i', ["Hello… I'm glad you could talk today.", "Hi there. How are you feeling?", "Hello. What's on your mind?"]],
        ['/hi(.*)/i', ["Hello… how are you today?", "Hey. What's going on?"]],
        ['/yes/i', ["You seem quite sure.", "OK, can you tell me more?", "I see."]],
        ['/no/i', ["Why not?", "Are you saying no just to be negative?", "Tell me more."]],
        ['/what (.*)/i', ["Why do you ask?", "What do you think?", "How would an answer help you?"]],
        ['/how (.*)/i', ["How do you suppose?", "What is it you're really asking?"]],
        ['/why (.*)/i', ["Why do you think {0}?", "What answer would feel right to you?"]],
        ['/(.*)\\?/i', ["Why do you ask that?", "What comes to mind when you ask that?", "Perhaps you already sense an answer."]],
        ['/(.*)/i', ["Please tell me more.", "That sounds important. Go on.", "Can you elaborate on that?", "I hear you. What else?", "How does that make you feel?", "Very interesting.", "{0}."]],
    ];

    foreach ($patterns as [$pattern, $responses]) {
        if (!preg_match($pattern, $text, $m)) {
            continue;
        }
        $groups = [];
        for ($i = 1; $i < count($m); $i++) {
            $groups[] = vox_eliza_reflect($m[$i]);
        }
        $template = $responses[array_rand($responses)];
        return preg_replace_callback('/\{(\d+)\}/', static function ($mm) use ($groups) {
            $idx = (int) $mm[1];
            return $groups[$idx] ?? '';
        }, $template) ?? $template;
    }

    return 'Tell me more.';
}
