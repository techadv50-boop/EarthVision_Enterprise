<?php
declare(strict_types=1);

/**
 * VoxPersona site config — edit on the server after upload if needed.
 */
return [
    'app_name' => 'VoxPersona',
    'app_url' => getenv('VOX_APP_URL') ?: 'http://localhost:5174',

    // Shown on signup / billing UI (monthly plan)
    'subscription_price' => getenv('VOX_SUBSCRIPTION_PRICE') ?: '9.99',
    'subscription_currency' => getenv('VOX_SUBSCRIPTION_CURRENCY') ?: 'USD',
    'subscription_days' => 30,

    // Remind this many days before subscription ends
    'reminder_days_before' => 5,

    // From address for PHP mail() on cPanel
    'mail_from' => getenv('VOX_MAIL_FROM') ?: 'noreply@example.com',
    'mail_from_name' => 'VoxPersona',

    // Seeded on first run
    'admin_email' => getenv('VOX_ADMIN_EMAIL') ?: 'admin@voxpersona.local',
    'admin_password' => getenv('VOX_ADMIN_PASSWORD') ?: 'Admin@123456',
    'admin_name' => 'Site Admin',

    // Optional shared secret for cron URL: /api/cron/reminders?key=...
    'cron_key' => getenv('VOX_CRON_KEY') ?: 'change-me-cron-key',

    /**
     * Discussion / analysis AI (OpenAI-compatible).
     * Works with OpenAI, Groq, OpenRouter, local Ollama proxies, etc.
     * Leave llm_api_key empty to use the built-in discussion engine + local speech analysis.
     */
    'llm_api_key' => getenv('VOX_LLM_API_KEY') ?: '',
    'llm_base_url' => getenv('VOX_LLM_BASE_URL') ?: 'https://api.openai.com/v1',
    'llm_model' => getenv('VOX_LLM_MODEL') ?: 'gpt-4o-mini',
];
