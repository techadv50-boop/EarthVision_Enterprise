"""Lightweight Eliza-style pattern chatbot."""

from __future__ import annotations

import random
import re

REFLECTIONS = {
    "am": "are",
    "was": "were",
    "i": "you",
    "i'd": "you would",
    "i've": "you have",
    "i'll": "you will",
    "my": "your",
    "are": "am",
    "you've": "I have",
    "you'll": "I will",
    "your": "my",
    "yours": "mine",
    "you": "me",
    "me": "you",
}

PATTERNS: list[tuple[str, list[str]]] = [
    (
        r"i need (.*)",
        [
            "Why do you need {0}?",
            "Would it really help you to get {0}?",
            "Are you sure you need {0}?",
        ],
    ),
    (
        r"why don'?t you ([^\?]*)\??",
        [
            "Do you really think I don't {0}?",
            "Perhaps eventually I will {0}.",
            "Do you really want me to {0}?",
        ],
    ),
    (
        r"why can'?t i ([^\?]*)\??",
        [
            "Do you think you should be able to {0}?",
            "If you could {0}, what would you do?",
            "I don't know — why can't you {0}?",
        ],
    ),
    (
        r"i can'?t (.*)",
        [
            "How do you know you can't {0}?",
            "Perhaps you could {0} if you tried.",
            "What would it take for you to {0}?",
        ],
    ),
    (
        r"i am (.*)",
        [
            "Did you come to me because you are {0}?",
            "How long have you been {0}?",
            "How do you feel about being {0}?",
        ],
    ),
    (
        r"i'?m (.*)",
        [
            "How does being {0} make you feel?",
            "Do you enjoy being {0}?",
            "Why do you tell me you're {0}?",
        ],
    ),
    (
        r"are you ([^\?]*)\??",
        [
            "Why does it matter whether I am {0}?",
            "Would you prefer if I were not {0}?",
            "Perhaps you believe I am {0}.",
        ],
    ),
    (
        r"what (.*)",
        [
            "Why do you ask?",
            "How would an answer to that help you?",
            "What do you think?",
        ],
    ),
    (
        r"how (.*)",
        [
            "How do you suppose?",
            "Perhaps you can answer your own question.",
            "What is it you're really asking?",
        ],
    ),
    (
        r"because (.*)",
        [
            "Is that the real reason?",
            "What other reasons come to mind?",
            "Does that reason explain anything else?",
        ],
    ),
    (
        r"(.*) sorry (.*)",
        [
            "There are many times when no apology is needed.",
            "What feelings do you have when you apologize?",
        ],
    ),
    (
        r"hello(.*)",
        [
            "Hello… I'm glad you could drop by today.",
            "Hi there… how are you feeling today?",
            "Hello there. What's on your mind?",
        ],
    ),
    (
        r"hi(.*)",
        [
            "Hello… how are you today?",
            "Hey. What's going on?",
        ],
    ),
    (
        r"i think (.*)",
        [
            "Do you doubt {0}?",
            "Do you really think so?",
            "But you're not sure {0}?",
        ],
    ),
    (
        r"(.*) friend (.*)",
        [
            "Tell me more about your friends.",
            "When you think of a friend, what comes to mind?",
        ],
    ),
    (
        r"yes",
        ["You seem quite sure.", "OK, but can you elaborate a bit?", "I see."],
    ),
    (
        r"no",
        [
            "Why not?",
            "Are you saying no just to be negative?",
            "You are being a bit short today.",
        ],
    ),
    (
        r"i feel (.*)",
        [
            "Tell me more about such feelings.",
            "Do you often feel {0}?",
            "When do you usually feel {0}?",
        ],
    ),
    (
        r"i have (.*)",
        [
            "Why do you tell me that you've {0}?",
            "Have you really {0}?",
            "Now that you have {0}, what will you do next?",
        ],
    ),
    (
        r"i would (.*)",
        [
            "Could you explain why you would {0}?",
            "Who else knows that you would {0}?",
        ],
    ),
    (
        r"is there (.*)",
        [
            "Do you think there is {0}?",
            "It's likely that there is {0}.",
            "Would you like there to be {0}?",
        ],
    ),
    (
        r"my (.*)",
        [
            "I see, your {0}.",
            "Why do you say that your {0}?",
            "When your {0}, how do you feel?",
        ],
    ),
    (
        r"you (.*)",
        [
            "We should be discussing you, not me.",
            "Why do you say that about me?",
            "Why do you care whether I {0}?",
        ],
    ),
    (
        r"why (.*)",
        ["Why don't you tell me the reason why {0}?", "Why do you think {0}?"],
    ),
    (
        r"i want (.*)",
        [
            "What would it mean to you if you got {0}?",
            "Why do you want {0}?",
            "What would you do if you got {0}?",
        ],
    ),
    (
        r"(.*)\?",
        [
            "Why do you ask that?",
            "Please consider whether you can answer your own question.",
            "Perhaps the answer lies within yourself.",
        ],
    ),
    (
        r"(.*)",
        [
            "Please tell me more.",
            "Let's change focus a bit… tell me about your family.",
            "Can you elaborate on that?",
            "Why do you say that {0}?",
            "I see.",
            "Very interesting.",
            "{0}.",
            "I see. And what does that tell you?",
            "How does that make you feel?",
            "How do you feel when you say that?",
        ],
    ),
]


def _reflect(fragment: str) -> str:
    words = fragment.lower().split()
    return " ".join(REFLECTIONS.get(word, word) for word in words)


def respond(user_input: str) -> str:
    text = user_input.strip()
    if not text:
        return "I'm listening. Tell me what's on your mind."

    for pattern, responses in PATTERNS:
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            continue
        groups = [_reflect(g) for g in match.groups()]
        template = random.choice(responses)
        try:
            return template.format(*groups)
        except IndexError:
            return template
    return "Tell me more."
