"""Academic English review for a manuscript going to publish.

Uses OpenAI when OPENAI_API_KEY is configured; always includes a local
checker so the wing works without an external key. Tools cover grammar,
sentence structure, abusive language, and related academic-English checks.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.services.matcher import is_references_heading, section_heading_kind
from app.services.reference_integrity import NUMBER_RE, paragraphs_from_upload

CATEGORIES = (
    "grammar",
    "agreement",
    "spelling",
    "punctuation",
    "capitalization",
    "sentence_structure",
    "broken_sentence",
    "run_on",
    "dangling_modifier",
    "parallelism",
    "slang",
    "formality",
    "second_person",
    "abusive",
    "bias_language",
    "cliche",
    "conciseness",
    "hedging",
    "redundancy",
    "irrelevant_word",
    "passive_voice",
    "overclaiming",
    "weasel",
    "opinion",
    "ambiguity",
    "clarity",
    "word_choice",
    "confused_words",
    "repetition",
    "anthropomorphism",
    "latin_abbrev",
    "hyphenation",
    "exclamation",
)

CATEGORY_ALIASES = {
    "english": "grammar",
    "wordiness": "conciseness",
    "tone": "formality",
    "informal": "slang",
    "filler": "irrelevant_word",
    "profanity": "abusive",
    "offensive": "abusive",
    "hate": "abusive",
    "abuse": "abusive",
    "hedge": "hedging",
    "tautology": "redundancy",
    "subject_verb": "agreement",
    "sva": "agreement",
    "comma_splice": "run_on",
    "fragment": "broken_sentence",
    "inclusive": "bias_language",
    "bias": "bias_language",
    "cliché": "cliche",
    "you": "second_person",
    "first_person": "opinion",
    "weasel_word": "weasel",
    "absolute": "overclaiming",
    "dangling": "dangling_modifier",
    "latin": "latin_abbrev",
    "confused": "confused_words",
    "hyphen": "hyphenation",
    "exclaim": "exclamation",
    "parallel": "parallelism",
}

TOOL_GROUPS = (
    {"id": "mechanics", "label": "Mechanics"},
    {"id": "sentences", "label": "Sentences"},
    {"id": "tone", "label": "Tone"},
    {"id": "style", "label": "Style"},
    {"id": "precision", "label": "Precision"},
)

TOOLS = (
    {
        "id": "grammar",
        "group": "mechanics",
        "label": "Grammar",
        "description": "Articles, verb form, and standard written English.",
    },
    {
        "id": "agreement",
        "group": "mechanics",
        "label": "Subject–verb agreement",
        "description": "Singular/plural subjects matched to the verb.",
    },
    {
        "id": "spelling",
        "group": "mechanics",
        "label": "Spelling",
        "description": "Common academic misspellings.",
    },
    {
        "id": "punctuation",
        "group": "mechanics",
        "label": "Punctuation",
        "description": "Commas, spaces, and repeated marks.",
    },
    {
        "id": "capitalization",
        "group": "mechanics",
        "label": "Capitalization",
        "description": "Sentence case and proper names.",
    },
    {
        "id": "sentence_structure",
        "group": "sentences",
        "label": "Sentence structure",
        "description": "Capital starts, length, and clause order.",
    },
    {
        "id": "broken_sentence",
        "group": "sentences",
        "label": "Broken sentence",
        "description": "Fragments and unfinished thoughts.",
    },
    {
        "id": "run_on",
        "group": "sentences",
        "label": "Run-on / comma splice",
        "description": "Independent clauses joined incorrectly.",
    },
    {
        "id": "dangling_modifier",
        "group": "sentences",
        "label": "Dangling modifier",
        "description": "Opening phrases that do not modify the subject.",
    },
    {
        "id": "parallelism",
        "group": "sentences",
        "label": "Parallelism",
        "description": "Matched grammar in lists and paired clauses.",
    },
    {
        "id": "slang",
        "group": "tone",
        "label": "Slang / informal",
        "description": "Colloquial words that do not belong in a journal.",
    },
    {
        "id": "formality",
        "group": "tone",
        "label": "Formality",
        "description": "Contractions and casual academic tone.",
    },
    {
        "id": "second_person",
        "group": "tone",
        "label": "Second person",
        "description": "You / your addressed to the reader.",
    },
    {
        "id": "abusive",
        "group": "tone",
        "label": "Abusive language",
        "description": "Profanity, insults, and hostile wording.",
    },
    {
        "id": "bias_language",
        "group": "tone",
        "label": "Inclusive language",
        "description": "Gendered or dated terms that can be recast.",
    },
    {
        "id": "cliche",
        "group": "tone",
        "label": "Cliché",
        "description": "Stock phrases that sound unscientific.",
    },
    {
        "id": "conciseness",
        "group": "style",
        "label": "Conciseness",
        "description": "Filler and wordy lead-ins.",
    },
    {
        "id": "hedging",
        "group": "style",
        "label": "Hedging",
        "description": "Empty intensifiers and vague mitigators.",
    },
    {
        "id": "redundancy",
        "group": "style",
        "label": "Redundancy",
        "description": "Tautologies such as true fact or past history.",
    },
    {
        "id": "irrelevant_word",
        "group": "style",
        "label": "Filler",
        "description": "Words that add no meaning.",
    },
    {
        "id": "passive_voice",
        "group": "style",
        "label": "Passive voice",
        "description": "Overused passive verbs when the actor is known.",
    },
    {
        "id": "overclaiming",
        "group": "style",
        "label": "Overclaiming",
        "description": "Absolute wording such as always, never, proves.",
    },
    {
        "id": "weasel",
        "group": "style",
        "label": "Weasel words",
        "description": "Unsupported 'it is known that' constructions.",
    },
    {
        "id": "opinion",
        "group": "style",
        "label": "Personal opinion",
        "description": "I think / I believe in place of evidence.",
    },
    {
        "id": "ambiguity",
        "group": "precision",
        "label": "Ambiguity",
        "description": "Unclear pronouns, open lists, and vague nouns.",
    },
    {
        "id": "clarity",
        "group": "precision",
        "label": "Clarity",
        "description": "Sentences that hide the claim.",
    },
    {
        "id": "word_choice",
        "group": "precision",
        "label": "Word choice",
        "description": "Imprecise or incorrect academic wording.",
    },
    {
        "id": "confused_words",
        "group": "precision",
        "label": "Confused words",
        "description": "Then/than, affect/effect, and similar pairs.",
    },
    {
        "id": "repetition",
        "group": "precision",
        "label": "Repetition",
        "description": "Immediate duplicate words.",
    },
    {
        "id": "anthropomorphism",
        "group": "precision",
        "label": "Anthropomorphism",
        "description": "Papers or results that 'believe' or 'think'.",
    },
    {
        "id": "latin_abbrev",
        "group": "precision",
        "label": "Latin abbreviations",
        "description": "e.g., i.e., etc., and et al. punctuation.",
    },
    {
        "id": "hyphenation",
        "group": "precision",
        "label": "Hyphenation",
        "description": "Compound adjectives that usually take a hyphen.",
    },
    {
        "id": "exclamation",
        "group": "precision",
        "label": "Exclamation",
        "description": "Exclamation marks in academic prose.",
    },
)

MISSPELLINGS: dict[str, str] = {
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperately": "separately",
    "occured": "occurred",
    "occurence": "occurrence",
    "definately": "definitely",
    "enviroment": "environment",
    "enviromental": "environmental",
    "measurment": "measurement",
    "analyis": "analysis",
    "analize": "analyze",
    "untill": "until",
    "wich": "which",
    "becuase": "because",
    "teh": "the",
    "adress": "address",
    "calender": "calendar",
    "existance": "existence",
    "independant": "independent",
    "neccessary": "necessary",
    "successfull": "successful",
    "accross": "across",
    "alot": "a lot",
    "publically": "publicly",
    "refered": "referred",
    "transfered": "transferred",
    "usefull": "useful",
    "arguement": "argument",
    "begining": "beginning",
    "catagory": "category",
    "commited": "committed",
    "comparision": "comparison",
    "concious": "conscious",
    "dissapear": "disappear",
    "embarras": "embarrass",
    "foriegn": "foreign",
    "goverment": "government",
    "hight": "height",
    "knowlege": "knowledge",
    "liason": "liaison",
    "maintainance": "maintenance",
    "noticable": "noticeable",
    "occassion": "occasion",
    "posession": "possession",
    "privelege": "privilege",
    "pronounciation": "pronunciation",
    "recomend": "recommend",
    "relevent": "relevant",
    "rythm": "rhythm",
    "sieze": "seize",
    "similiar": "similar",
    "strenght": "strength",
    "sucess": "success",
    "thier": "their",
    "tommorrow": "tomorrow",
    "truely": "truly",
    "unfortunatly": "unfortunately",
    "wether": "whether",
    "whereever": "wherever",
    "writting": "writing",
}

WORD_CHOICE: dict[str, str] = {
    "irregardless": "regardless",
    "utilize": "use",
    "utilized": "used",
    "utilization": "use",
    "amongst": "among",
    "whilst": "while",
    "towards": "toward",
    "impacted": "affected",
    "very unique": "unique",
    "could of": "could have",
    "should of": "should have",
    "would of": "would have",
    "must of": "must have",
    "less people": "fewer people",
    "amount of people": "number of people",
    "comprised of": "composed of / consisted of",
    "based off of": "based on",
    "different than": "different from",
    "in regards to": "regarding / with regard to",
}

CONTRACTIONS: dict[str, str] = {
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "can't": "cannot",
    "won't": "will not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "it's": "it is / it has",
    "they're": "they are",
    "we're": "we are",
    "you're": "you are",
    "there's": "there is",
    "let's": "let us",
    "that's": "that is",
    "who's": "who is",
}

SLANG: dict[str, str] = {
    "gonna": "going to",
    "wanna": "want to",
    "gotta": "must / have to",
    "kinda": "somewhat / rather",
    "sorta": "somewhat / rather",
    "yeah": "yes",
    "yep": "yes",
    "nope": "no",
    "ok": "acceptable / satisfactory",
    "okay": "acceptable / satisfactory",
    "cool": "suitable / effective (choose a precise adjective)",
    "awesome": "substantial / notable",
    "guys": "participants / researchers / readers",
    "kids": "children",
    "folks": "people / participants",
    "stuff": "material / data / items",
    "a lot of": "many / a large number of",
    "lots of": "many / numerous",
    "bunch of": "several / a group of",
    "pretty much": "almost / nearly",
    "kind of": "somewhat",
    "sort of": "somewhat",
    "ain't": "is not / are not",
    "dunno": "is not known / remains unknown",
    "y'all": "all of you / the participants",
    "gimme": "give me",
    "lemme": "allow me / let me",
    "cuz": "because",
    "'cause": "because",
    "till": "until",
    "thru": "through",
    "info": "information",
    "stats": "statistics",
    "asap": "as soon as possible (prefer a specific deadline)",
    "btw": "omit, or write the connection explicitly",
    "imo": "omit informal aside",
    "lol": "omit",
    "wow": "omit",
    "sucks": "is inadequate / is unsuitable",
    "crap": "omit; use a precise description",
    "hell": "omit informal intensifier",
    "damn": "omit informal intensifier",
    "huge": "large / substantial (quantify if possible)",
    "crazy": "unexpected / irregular",
    "super": "highly / very (prefer a measured term)",
    "totally": "entirely / completely (or omit)",
    "literally": "omit unless used in the literal sense",
    "basically": "omit, or state the claim directly",
    "actually": "omit unless contrasting a prior claim",
    "dude": "omit",
    "bro": "omit",
    "lmao": "omit",
    "omg": "omit",
    "tbh": "omit",
    "idk": "is not known / remains unknown",
    "ngl": "omit",
    "lowkey": "omit",
    "vibe": "omit informal wording",
    "lit": "omit informal wording",
    "salty": "omit informal wording",
    "meh": "omit",
    "nah": "no",
    "yikes": "omit",
}

# Multi-word first so they are not split by the single-word pass.
SLANG_PHRASES = [
    "a lot of",
    "lots of",
    "bunch of",
    "pretty much",
    "kind of",
    "sort of",
]

FILLER_PHRASES: dict[str, str] = {
    "in order to": "to",
    "due to the fact that": "because",
    "in spite of the fact that": "although",
    "at this point in time": "now / at this stage",
    "it is important to note that": "omit the lead-in; state the point",
    "it should be noted that": "omit the lead-in; state the point",
    "needless to say": "omit",
    "as a matter of fact": "omit",
    "the fact that": "rephrase without this filler",
    "in terms of": "about / regarding (or recast the sentence)",
    "a number of": "several / many (prefer a count)",
    "in the event that": "if",
    "for the purpose of": "to / for",
    "with regard to": "about / regarding",
    "on the other hand": "by contrast (or split the contrast)",
    "in light of the fact that": "because",
    "with a view to": "to",
    "in the near future": "soon / by a named date",
    "at the present time": "now / currently",
    "in the majority of cases": "usually / in most cases (prefer a percentage)",
    "has the ability to": "can",
    "is able to": "can",
    "make a decision": "decide",
    "conduct an investigation": "investigate",
}

HEDGING_PHRASES: dict[str, str] = {
    "it seems that": "state the finding directly, or name the evidence",
    "it appears that": "state the finding directly, or name the evidence",
    "it could be argued that": "state the claim and the support",
    "to some extent": "quantify the extent, or omit",
    "more or less": "omit, or give the range",
    "in a sense": "omit, or specify the sense",
    "to a certain extent": "quantify the extent, or omit",
    "it may be that": "state the finding or the uncertainty with evidence",
    "it is possible that": "state the probability or the supporting result",
    "perhaps": "omit, or give the evidence for uncertainty",
}

REDUNDANT_PHRASES: dict[str, str] = {
    "each and every": "each / every",
    "end result": "result",
    "final outcome": "outcome",
    "advance planning": "planning",
    "past history": "history",
    "future plans": "plans",
    "true fact": "fact",
    "basic fundamentals": "fundamentals",
    "close proximity": "proximity / near",
    "completely unique": "unique",
    "unexpected surprise": "surprise",
    "free gift": "gift",
    "revert back": "revert",
    "repeat again": "repeat",
    "still remains": "remains",
    "added bonus": "bonus",
    "exact same": "same",
    "new innovation": "innovation",
    "reason why": "reason",
    "whether or not": "whether (unless the 'or not' is required)",
    "period of time": "period",
    "summarize briefly": "summarize",
}

ABUSIVE_WORDS: dict[str, str] = {
    "stupid": "omit the insult; describe the limitation of the method or result",
    "idiot": "omit the insult",
    "idiotic": "omit the insult; describe the limitation",
    "dumb": "omit the insult; use a precise critique",
    "moron": "omit the insult",
    "imbecile": "omit the insult",
    "retard": "omit; this wording is abusive and unsuitable for publication",
    "retarded": "omit; this wording is abusive and unsuitable for publication",
    "hate": "omit hostile wording, or recast as a technical disagreement",
    "shut up": "omit",
    "crap": "omit; use a precise description",
    "shit": "omit profanity",
    "shitty": "omit profanity",
    "fuck": "omit profanity",
    "fucking": "omit profanity",
    "fucked": "omit profanity",
    "bullshit": "omit profanity; state the objection",
    "bitch": "omit abusive wording",
    "bastard": "omit abusive wording",
    "asshole": "omit abusive wording",
    "dick": "omit abusive wording",
    "piss": "omit profanity",
    "pissed": "omit profanity",
    "slut": "omit abusive wording",
    "whore": "omit abusive wording",
    "worthless": "omit the insult; describe the limitation",
    "pathetic": "omit the insult; describe the limitation",
    "garbage": "omit abusive wording; use a precise critique",
    "trash": "omit abusive wording; use a precise critique",
    "sucks": "is inadequate / is unsuitable",
    "suck": "omit abusive wording",
    "bloody": "omit informal intensifier",
    "dumbass": "omit the insult",
    "jackass": "omit the insult",
    "loser": "omit the insult",
    "nasty": "omit hostile wording, or use a precise technical term",
}

AGREEMENT_PATTERNS = (
    (r"\bresults was\b", "results were"),
    (r"\bthis methods\b", "these methods / this method"),
    (r"\bthese method\b", "this method / these methods"),
    (r"\bthere is many\b", "there are many"),
    (r"\bthere is several\b", "there are several"),
    (r"\bthere are a\b", "there is a"),
    (r"\bthe data shows\b", "the data show (if treating data as plural)"),
    (r"\beach of the \w+ were\b", "each of the … was"),
    (r"\bone of the \w+ were\b", "one of the … was"),
)

CLICHE_PHRASES: dict[str, str] = {
    "in this day and age": "currently / today",
    "at the end of the day": "omit, or state the conclusion",
    "last but not least": "finally",
    "in a nutshell": "in summary",
    "food for thought": "omit; state the implication",
    "only time will tell": "omit; state what remains unknown",
    "it goes without saying": "omit",
    "tip of the iceberg": "omit; quantify the remaining gap",
    "think outside the box": "omit; name the alternative approach",
    "in the long run": "over the longer term (name the period)",
    "a mixed bag": "mixed results (be specific)",
}

BIAS_PHRASES: dict[str, str] = {
    "mankind": "humankind / people",
    "manpower": "staff / workforce",
    "chairman": "chair / chairperson",
    "policeman": "police officer",
    "policemen": "police officers",
    "freshman": "first-year student",
    "man-made": "synthetic / anthropogenic",
    "manned": "crewed / staffed",
}

WEASEL_PHRASES: dict[str, str] = {
    "it is known that": "cite the source, or state the finding",
    "it is believed that": "name who believes it and on what evidence",
    "it has been said that": "cite the source",
    "some researchers say": "name the researchers and the evidence",
    "many people think": "cite a source, or omit",
    "it is clear that": "state the evidence that makes it clear",
    "needless to say": "omit",
}

OPINION_PHRASES: dict[str, str] = {
    "i think": "state the claim and the support",
    "i believe": "state the claim and the support",
    "i feel": "state the finding; feelings are not evidence",
    "we feel": "state the finding",
    "in my opinion": "omit; present the evidence",
    "personally": "omit",
    "i would argue": "state the argument and the support",
}

ANTHROPOMORPHISM_PATTERNS = (
    (r"\b(this|the)\s+(paper|study|article|research)\s+(believes|thinks|feels|hopes|tries|wants)\b",
     "Recast so the authors perform the action, e.g. 'We argue' or 'This study shows'."),
    (r"\b(the|these)\s+(results|data|findings)\s+(believe|think|feel|hope)\b",
     "Results cannot believe or think. State what they show."),
)

CONFUSED_PATTERNS = (
    (r"\bmore then\b", "more than"),
    (r"\bless then\b", "less than"),
    (r"\bbetter then\b", "better than"),
    (r"\bworse then\b", "worse than"),
    (r"\brather then\b", "rather than"),
    (r"\bother then\b", "other than"),
    (r"\bthe affect of\b", "the effect of"),
    (r"\ban affect\b", "an effect"),
    (r"\bprinciple investigator\b", "principal investigator"),
    (r"\bits'\b", "its"),
    (r"\bbetween you and i\b", "between you and me"),
    (r"\bcould care less\b", "could not care less"),
    (r"\bshould of\b", "should have"),
)

HYPHEN_PHRASES: dict[str, str] = {
    "well known": "well-known (when used as an adjective before a noun)",
    "high resolution": "high-resolution (when used as an adjective before a noun)",
    "real time": "real-time (when used as an adjective before a noun)",
    "peer reviewed": "peer-reviewed (when used as an adjective before a noun)",
    "open source": "open-source (when used as an adjective before a noun)",
    "state of the art": "state-of-the-art (when used as an adjective before a noun)",
    "long term": "long-term (when used as an adjective before a noun)",
    "short term": "short-term (when used as an adjective before a noun)",
}

OVERCLAIMING_PATTERNS = (
    (r"\balways\b", "always — qualify the claim unless it is literally universal"),
    (r"\bnever\b", "never — qualify the claim unless it is literally universal"),
    (r"\bproves that\b", "shows that / indicates that (unless a formal proof)"),
    (r"\bproven that\b", "shown that / indicated that"),
    (r"\bobviously\b", "omit, or state the evidence"),
    (r"\bundoubtedly\b", "omit, or state the evidence"),
    (r"\beveryone knows\b", "cite a source; do not assume shared knowledge"),
)

DANGLING_RE = re.compile(
    r"\b(?:After|When|While|By|Using|Based on|Having|Considering)\s+"
    r"(?:[A-Za-z]+ing|[A-Za-z]+ed)\b[^.]{0,90},\s+the\s+"
    r"(?:results?|data|findings?|analysis|paper|study|model)\b",
    re.I,
)

LATIN_ABBREV_PATTERNS = (
    (r"\beg\b(?!\.)", "e.g."),
    (r"\bie\b(?!\.)", "i.e."),
    (r"\betc\b(?!\.)", "etc."),
    (r"\bet al\b(?!\.)", "et al."),
)

AMBIGUOUS_OPENERS = {"this", "that", "these", "those", "it", "they", "them"}

HEADING_SKIP_RE = re.compile(
    r"^(abstract|keywords?|introduction|materials and methods|methodology|"
    r"methods|results|discussion|conclusion|references|acknowledgements?)\b",
    re.I,
)

ABBREV_SAFE = re.compile(
    r"\b(e\.g|i\.e|et al|fig|figs|eq|eqs|vol|no|dr|prof|vs|cf|ref|refs)\.$",
    re.I,
)


def _is_heading(text: str) -> bool:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return True
    if is_references_heading(compact):
        return True
    if section_heading_kind(compact):
        return True
    if HEADING_SKIP_RE.match(compact) and len(compact.split()) <= 10 and not compact.endswith("."):
        return True
    return False


def _is_reference_line(text: str) -> bool:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return bool(NUMBER_RE.match(compact)) and len(compact) > 20


def split_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return []
    parts: list[str] = []
    buf: list[str] = []
    tokens = re.split(r"(\s+)", compact)
    for token in tokens:
        buf.append(token)
        piece = "".join(buf)
        if re.search(r"[.!?][\"')\]]*$", piece) and not ABBREV_SAFE.search(piece.rstrip()):
            # Avoid splitting 3.14 or Fig. 2 mid-number after abbrev already handled.
            parts.append(piece.strip())
            buf = []
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text or ""))


def _add_issue(
    issues: list[dict[str, Any]],
    *,
    paragraph_index: int,
    quote: str,
    category: str,
    suggestion: str,
    explanation: str,
    severity: str = "medium",
    rewrite: str = "",
) -> None:
    quote = re.sub(r"\s+", " ", (quote or "").strip())
    if not quote:
        return
    key = (paragraph_index, category, quote.lower()[:160])
    if any((i["paragraph_index"], i["category"], i["quote"].lower()[:160]) == key for i in issues):
        return
    issues.append(
        {
            "paragraph_index": paragraph_index,
            "quote": quote[:400],
            "category": category,
            "severity": severity,
            "suggestion": suggestion,
            "explanation": explanation,
            "rewrite": (rewrite or "").strip()[:500],
            "source": "local",
        }
    )


def review_paragraph_local(index: int, text: str, *, in_references: bool) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact or _is_heading(compact):
        return issues
    if in_references or _is_reference_line(compact):
        return issues

    lower = compact.lower()
    for phrase in SLANG_PHRASES:
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="slang",
                severity="high",
                suggestion=SLANG.get(phrase, "Use a formal equivalent."),
                rewrite=SLANG.get(phrase, ""),
                explanation="Informal phrasing is not suitable for a paper going to publish.",
            )
    for phrase, replacement in FILLER_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="conciseness",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Filler phrasing weakens academic English; prefer a direct wording.",
            )

    for match in re.finditer(r"\b[A-Za-z']+\b", compact):
        word = match.group(0)
        key = word.lower()
        if key in SLANG and key not in ABUSIVE_WORDS:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=word,
                category="slang" if key not in {"basically", "actually", "literally", "totally", "super", "huge"} else (
                    "irrelevant_word" if key in {"basically", "actually", "literally", "totally"} else "slang"
                ),
                severity="high" if key in {"gonna", "wanna", "ain't", "yeah", "ok", "okay", "stuff", "kids"} else "medium",
                suggestion=SLANG[key],
                rewrite=SLANG[key],
                explanation="This word is informal, slang, or too vague for a journal manuscript.",
            )

    if re.search(r"\b(etc\.|and so on|and so forth|and others like that)\b", compact, re.I):
        quote = re.search(r"etc\.|and so on|and so forth|and others like that", compact, re.I)
        _add_issue(
            issues,
            paragraph_index=index,
            quote=quote.group(0) if quote else "etc.",
            category="ambiguity",
            severity="medium",
            suggestion="Name the remaining items, or delete the open-ended list.",
            explanation="Open-ended lists leave the reader unsure what is included.",
        )

    if re.search(r"\b(some aspects|various things|many things|several things|this thing|the things)\b", compact, re.I):
        quote = re.search(
            r"some aspects|various things|many things|several things|this thing|the things",
            compact,
            re.I,
        )
        _add_issue(
            issues,
            paragraph_index=index,
            quote=quote.group(0) if quote else "things",
            category="ambiguity",
            severity="medium",
            suggestion="Name the specific factors, variables, or objects.",
            explanation="Vague nouns hide the claim. State what is meant.",
        )

    if re.search(r"\b(\w+)\s+\1\b", compact, re.I):
        dup = re.search(r"\b(\w+)\s+\1\b", compact, re.I)
        if dup and dup.group(1).lower() not in {"had", "that"}:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=dup.group(0),
                category="repetition",
                severity="high",
                suggestion=dup.group(1),
                explanation="Repeated word; keep a single copy.",
            )

    sentences = split_sentences(compact)
    if not sentences:
        sentences = [compact]

    for sent in sentences:
        words = _word_count(sent)
        stripped = sent.strip()
        if words >= 8 and not re.search(r"[.!?…][\"')\]]*$", stripped) and not stripped.endswith(":"):
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[:220],
                category="broken_sentence",
                severity="high",
                suggestion="Finish the sentence and end it with a period (or ? / !).",
                explanation="This stretch reads as an unfinished sentence.",
            )
        if re.search(r"[,;:]\s*$", stripped) or re.search(
            r"\b(and|or|but|because|which|that|if|when|although|while)\s*$",
            stripped,
            re.I,
        ):
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[-80:] if len(stripped) > 80 else stripped,
                category="broken_sentence",
                severity="high",
                suggestion="Complete the clause; do not leave the sentence hanging.",
                explanation="The sentence ends on a conjunction or comma, so the thought is incomplete.",
            )
        if stripped and stripped[0].islower() and words >= 6 and not stripped.startswith(("e.g", "i.e", "n=", "p=")):
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[:120],
                category="sentence_structure",
                severity="medium",
                suggestion="Start the sentence with a capital letter, or join it to the previous sentence.",
                explanation="A mid-thought start usually means a broken or poorly split sentence.",
            )
        if words >= 42:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[:240],
                category="sentence_structure",
                severity="medium",
                suggestion="Split into two or three shorter sentences with one idea each.",
                explanation="Very long sentences are hard to follow and often hide grammar faults.",
            )
        if len(re.findall(r"\b(and|but|so|then)\b", stripped, re.I)) >= 4 and words >= 28:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[:220],
                category="run_on",
                severity="medium",
                suggestion="Break the run-on into separate sentences.",
                explanation="Stacked conjunctions usually signal a run-on sentence.",
            )
        first = re.match(r"^([A-Za-z']+)", stripped)
        if first and first.group(1).lower() in AMBIGUOUS_OPENERS and words <= 18:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=stripped[:160],
                category="ambiguity",
                severity="low",
                suggestion="Name the noun that this / it / they refers to.",
                explanation="Opening with a pronoun can leave the antecedent unclear.",
            )

    if compact.count(",") >= 1 and re.search(r",[A-Za-z]", compact):
        _add_issue(
            issues,
            paragraph_index=index,
            quote=re.search(r",[A-Za-z]", compact).group(0) if re.search(r",[A-Za-z]", compact) else ",",
            category="punctuation",
            severity="low",
            suggestion="Add a space after the comma.",
            explanation="Missing space after a comma.",
        )

    for wrong, right in MISSPELLINGS.items():
        if re.search(rf"\b{re.escape(wrong)}\b", compact, re.I):
            found = re.search(rf"\b{re.escape(wrong)}\b", compact, re.I)
            _add_issue(
                issues,
                paragraph_index=index,
                quote=found.group(0) if found else wrong,
                category="spelling",
                severity="high",
                suggestion=right,
                rewrite=right,
                explanation="Likely spelling error.",
            )

    for wrong, right in WORD_CHOICE.items():
        if wrong in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=wrong,
                category="word_choice",
                severity="medium",
                suggestion=right,
                rewrite=right,
                explanation="Prefer the precise academic wording.",
            )

    for wrong, right in CONTRACTIONS.items():
        if re.search(rf"\b{re.escape(wrong)}\b", compact, re.I):
            found = re.search(rf"\b{re.escape(wrong)}\b", compact, re.I)
            _add_issue(
                issues,
                paragraph_index=index,
                quote=found.group(0) if found else wrong,
                category="formality",
                severity="medium",
                suggestion=right,
                rewrite=right,
                explanation="Contractions are too informal for a journal manuscript.",
            )

    if re.search(r"\s{2,}", text or ""):
        _add_issue(
            issues,
            paragraph_index=index,
            quote="  ",
            category="punctuation",
            severity="low",
            suggestion="Use a single space.",
            explanation="Double spaces should be removed.",
        )
    if re.search(r"\s+[,.;:]", compact):
        hit = re.search(r"\s+[,.;:]", compact)
        _add_issue(
            issues,
            paragraph_index=index,
            quote=hit.group(0) if hit else " ,",
            category="punctuation",
            severity="low",
            suggestion="Remove the space before the punctuation mark.",
            explanation="English punctuation sits against the preceding word.",
        )
    if re.search(r"[!?]{2,}|\.{4,}", compact):
        _add_issue(
            issues,
            paragraph_index=index,
            quote=re.search(r"[!?]{2,}|\.{4,}", compact).group(0),
            category="punctuation",
            severity="medium",
            suggestion="Use a single period or question mark.",
            explanation="Repeated punctuation is not used in academic prose.",
        )

    for match in re.finditer(r"\b(a|an)\s+([A-Za-z]+)", compact, re.I):
        article, noun = match.group(1).lower(), match.group(2)
        starts_vowel = noun[0].lower() in "aeiou"
        if article == "a" and starts_vowel and noun.lower() not in {"one", "once", "unit", "use", "used", "european", "university"}:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=match.group(0),
                category="grammar",
                severity="high",
                suggestion=f"an {noun}",
                rewrite=f"an {noun}",
                explanation="Use 'an' before a vowel sound.",
            )
        if article == "an" and not starts_vowel and noun[0].lower() not in "aeiou":
            _add_issue(
                issues,
                paragraph_index=index,
                quote=match.group(0),
                category="grammar",
                severity="high",
                suggestion=f"a {noun}",
                rewrite=f"a {noun}",
                explanation="Use 'a' before a consonant sound.",
            )

    if re.search(r"\b(data is|this data was)\b", compact, re.I):
        hit = re.search(r"\b(data is|this data was)\b", compact, re.I)
        _add_issue(
            issues,
            paragraph_index=index,
            quote=hit.group(0) if hit else "data is",
            category="grammar",
            severity="low",
            suggestion="data are / these data were (if treating data as plural)",
            explanation="In many journals 'data' is treated as a plural noun.",
        )

    if re.search(r"\b(very|really|quite|extremely)\s+\w+", compact, re.I):
        hits = list(re.finditer(r"\b(very|really|quite|extremely)\s+\w+", compact, re.I))
        if len(hits) >= 2:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hits[0].group(0),
                category="conciseness",
                severity="low",
                suggestion="Replace intensifiers with a precise measure or omit them.",
                explanation="Repeated intensifiers weaken academic tone.",
            )

    if re.search(r"\b(was|were|been|being)\s+\w+ed\b", compact, re.I) and _word_count(compact) >= 12:
        hit = re.search(r"\b(?:was|were|been|being)\s+\w+ed\b", compact, re.I)
        _add_issue(
            issues,
            paragraph_index=index,
            quote=hit.group(0) if hit else "was performed",
            category="passive_voice",
            severity="low",
            suggestion="Prefer an active verb where the actor is known.",
            explanation="Passive voice is common in methods, but overuse hides who did the work.",
        )

    if re.search(r"^[A-Za-z].+,[A-Za-z].+\s+(and|but)\s+[a-z]", compact) and compact.count(",") >= 1:
        if re.search(r",[A-Za-z].{10,}(and|but)\s", compact):
            _add_issue(
                issues,
                paragraph_index=index,
                quote=compact[:160],
                category="run_on",
                severity="medium",
                suggestion="Split the comma splice into two sentences, or use a semicolon.",
                explanation="Two independent clauses joined by only a comma form a comma splice.",
            )

    for phrase, replacement in HEDGING_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="hedging",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Hedging without evidence weakens the claim. Be specific or omit.",
            )

    for phrase, replacement in REDUNDANT_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="redundancy",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="This pairing repeats the same idea. Keep one term.",
            )

    for word, replacement in ABUSIVE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", compact, re.I):
            found = re.search(rf"\b{re.escape(word)}\b", compact, re.I)
            _add_issue(
                issues,
                paragraph_index=index,
                quote=found.group(0) if found else word,
                category="abusive",
                severity="high",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Abusive, insulting, or profane wording is not acceptable in a journal manuscript.",
            )

    for pattern, replacement in AGREEMENT_PATTERNS:
        hit = re.search(pattern, compact, re.I)
        if hit:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hit.group(0),
                category="agreement",
                severity="high",
                suggestion=replacement,
                rewrite=replacement,
                explanation="The subject and verb do not agree in number.",
            )

    for phrase, replacement in CLICHE_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="cliche",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="This stock phrase is too casual or empty for a journal manuscript.",
            )

    for phrase, replacement in BIAS_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="bias_language",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Prefer inclusive or precise wording.",
            )

    for phrase, replacement in WEASEL_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="weasel",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="This construction hides the source. Cite evidence or omit.",
            )

    for phrase, replacement in OPINION_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="opinion",
                severity="medium",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Personal opinion should be replaced by a claim with evidence.",
            )

    for phrase, replacement in HYPHEN_PHRASES.items():
        if phrase in lower:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=phrase,
                category="hyphenation",
                severity="low",
                suggestion=replacement,
                rewrite=replacement.split(" (")[0],
                explanation="Compound adjectives before a noun usually take hyphens.",
            )

    for pattern, replacement in ANTHROPOMORPHISM_PATTERNS:
        hit = re.search(pattern, compact, re.I)
        if hit:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hit.group(0),
                category="anthropomorphism",
                severity="medium",
                suggestion=replacement,
                explanation="A paper or result cannot think or believe. Recast with the authors or a verb such as show.",
            )

    for pattern, replacement in CONFUSED_PATTERNS:
        hit = re.search(pattern, compact, re.I)
        if hit:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hit.group(0),
                category="confused_words",
                severity="high",
                suggestion=replacement,
                rewrite=replacement,
                explanation="These look-alike words are easy to mix up.",
            )

    for pattern, replacement in OVERCLAIMING_PATTERNS:
        hit = re.search(pattern, compact, re.I)
        if hit:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hit.group(0),
                category="overclaiming",
                severity="medium",
                suggestion=replacement,
                explanation="Absolute wording overstates the result unless the claim is truly universal.",
            )

    for pattern, replacement in LATIN_ABBREV_PATTERNS:
        hit = re.search(pattern, compact, re.I)
        if hit:
            _add_issue(
                issues,
                paragraph_index=index,
                quote=hit.group(0),
                category="latin_abbrev",
                severity="low",
                suggestion=replacement,
                rewrite=replacement,
                explanation="Latin abbreviations in academic English take standard punctuation.",
            )

    you_hit = re.search(r"\b(you|your|yours)\b(?!')", compact, re.I)
    if you_hit:
        _add_issue(
            issues,
            paragraph_index=index,
            quote=you_hit.group(0),
            category="second_person",
            severity="medium",
            suggestion="Recast without addressing the reader (use one / the researcher / the method).",
            explanation="Second person is too informal for a journal manuscript.",
        )

    dangling = DANGLING_RE.search(compact)
    if dangling:
        _add_issue(
            issues,
            paragraph_index=index,
            quote=dangling.group(0)[:220],
            category="dangling_modifier",
            severity="high",
            suggestion="Make the subject of the main clause the actor of the opening phrase.",
            explanation="The opening phrase does not modify the grammatical subject.",
        )

    if "!" in compact:
        bang = re.search(r"!+", compact)
        _add_issue(
            issues,
            paragraph_index=index,
            quote=bang.group(0) if bang else "!",
            category="exclamation",
            severity="medium",
            suggestion="Use a period. Exclamation marks are not used in academic prose.",
            rewrite=".",
            explanation="Exclamation marks read as informal or rhetorical, not scientific.",
        )

    return issues


def review_local(paragraphs: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    in_references = False
    for index, text in enumerate(paragraphs):
        if is_references_heading(text):
            in_references = True
        issues.extend(review_paragraph_local(index, text, in_references=in_references))
    return issues


def _assign_ids(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, issue in enumerate(issues, start=1):
        row = dict(issue)
        row["id"] = i
        row.setdefault("rewrite", "")
        row.setdefault("source", "local")
        out.append(row)
    return out


def _summarize(paragraphs: list[str], issues: list[dict[str, Any]]) -> dict[str, Any]:
    by_category = {key: 0 for key in CATEGORIES}
    by_severity = {"high": 0, "medium": 0, "low": 0}
    for issue in issues:
        cat = issue.get("category") or "grammar"
        cat = CATEGORY_ALIASES.get(cat, cat)
        issue["category"] = cat
        if cat not in by_category:
            by_category[cat] = 0
        by_category[cat] += 1
        sev = issue.get("severity") or "medium"
        by_severity[sev] = by_severity.get(sev, 0) + 1
    penalty = by_severity.get("high", 0) * 6 + by_severity.get("medium", 0) * 3 + by_severity.get("low", 0)
    score = max(0, min(100, 100 - penalty))
    if score >= 90:
        band = "Excellent"
    elif score >= 75:
        band = "Good"
    elif score >= 55:
        band = "Needs revision"
    else:
        band = "Poor"
    return {
        "paragraph_count": len(paragraphs),
        "issue_count": len(issues),
        "by_category": by_category,
        "by_severity": by_severity,
        "score": score,
        "band": band,
        "verdict": (
            f"Overall English score {score}/100 ({band}). "
            f"{len(issues)} suggestion(s) across grammar, style, and clarity."
        ),
    }


async def _openai_review(paragraphs: list[str]) -> tuple[list[dict[str, Any]], Optional[str]]:
    settings = get_settings()
    key = (getattr(settings, "openai_api_key", None) or "").strip()
    if not key:
        return [], None
    model = (getattr(settings, "openai_model", None) or "gpt-4o-mini").strip()
    base = (getattr(settings, "openai_base_url", None) or "https://api.openai.com/v1").rstrip("/")

    numbered: list[tuple[int, str]] = []
    in_references = False
    for index, text in enumerate(paragraphs):
        compact = re.sub(r"\s+", " ", (text or "").strip())
        if is_references_heading(compact):
            in_references = True
        if not compact or _is_heading(compact) or in_references or _is_reference_line(compact):
            continue
        numbered.append((index, compact[:2500]))

    if not numbered:
        return [], None

    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for item in numbered:
        extra = len(item[1]) + 20
        if current and size + extra > 9000:
            chunks.append(current)
            current = []
            size = 0
        current.append(item)
        size += extra
    if current:
        chunks.append(current)

    collected: list[dict[str, Any]] = []
    category_pipe = "|".join(CATEGORIES)
    system = (
        "You are a Grammarly-style academic English editor for a scientific journal. "
        "Check every issue type in this list: grammar, subject-verb agreement, spelling, "
        "punctuation, capitalization, sentence structure, broken/fragment sentences, "
        "run-on sentences and comma splices, dangling modifiers, parallelism, slang and "
        "informal wording, formality and contractions, second person (you/your), abusive "
        "language and profanity, inclusive/bias language, clichés, conciseness, hedging, "
        "redundancy, filler, passive voice, overclaiming (always/never/proves), weasel "
        "words, personal opinion (I think/I believe), ambiguity, clarity, word choice, "
        "confused word pairs, repetition, anthropomorphism, Latin abbreviations, "
        "hyphenation of compound adjectives, and exclamation marks. "
        "Flag abusive, insulting, or profane wording as category 'abusive' with high severity. "
        "Do not rewrite the whole paper. Do not comment on scientific correctness. "
        "Quotes MUST be exact substrings of the given paragraph. "
        "For each issue also give a short 'rewrite' that replaces only the quoted span "
        "with a publishable wording. "
        "Return JSON: {\"issues\":[{\"paragraph_index\":0,\"quote\":\"...\",\"category\":"
        f"\"{category_pipe}\","
        "\"severity\":\"high|medium|low\",\"suggestion\":\"...\",\"explanation\":\"...\","
        "\"rewrite\":\"...\"}]}"
    )
    timeout = httpx.Timeout(90.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for chunk in chunks[:8]:
            body = "\n\n".join(f"[paragraph {idx}]\n{text}" for idx, text in chunk)
            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system},
                            {
                                "role": "user",
                                "content": "Review these manuscript paragraphs:\n\n" + body,
                            },
                        ],
                    },
                )
            except Exception as exc:
                return collected, f"openai-error:{exc.__class__.__name__}"
            if response.status_code >= 400:
                return collected, f"openai-http-{response.status_code}"
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except Exception:
                return collected, "openai-bad-response"
            content = (content or "").strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            rows = payload.get("issues") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            allowed = {idx for idx, _ in chunk}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    pidx = int(row.get("paragraph_index"))
                except (TypeError, ValueError):
                    continue
                if pidx not in allowed:
                    continue
                quote = str(row.get("quote") or "").strip()
                if not quote:
                    continue
                cat = str(row.get("category") or "grammar").strip().lower().replace(" ", "_")
                cat = CATEGORY_ALIASES.get(cat, cat)
                if cat not in CATEGORIES:
                    cat = "grammar"
                sev = str(row.get("severity") or "medium").strip().lower()
                if sev not in {"high", "medium", "low"}:
                    sev = "medium"
                rewrite = str(
                    row.get("rewrite") or row.get("correction") or row.get("replacement") or ""
                ).strip()
                collected.append(
                    {
                        "paragraph_index": pidx,
                        "quote": quote[:400],
                        "category": cat,
                        "severity": sev,
                        "suggestion": str(row.get("suggestion") or "").strip()[:500],
                        "explanation": str(row.get("explanation") or "").strip()[:600],
                        "rewrite": rewrite[:500],
                        "source": "openai",
                    }
                )
    return collected, "openai"


def _merge_issues(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: dict[tuple[Any, ...], int] = {}
    for issue in remote + local:
        quote = re.sub(r"\s+", " ", (issue.get("quote") or "").strip()).lower()[:160]
        key = (issue.get("paragraph_index"), issue.get("category"), quote)
        if key in seen:
            idx = seen[key]
            if not (merged[idx].get("rewrite") or "").strip() and (issue.get("rewrite") or "").strip():
                merged[idx]["rewrite"] = issue["rewrite"]
            continue
        seen[key] = len(merged)
        merged.append(issue)
    merged.sort(
        key=lambda row: (
            int(row.get("paragraph_index") or 0),
            {"high": 0, "medium": 1, "low": 2}.get(row.get("severity") or "", 3),
        )
    )
    return merged


def gpt_status() -> dict[str, Any]:
    settings = get_settings()
    key = (getattr(settings, "openai_api_key", None) or "").strip()
    model = (getattr(settings, "openai_model", None) or "gpt-4o-mini").strip()
    if key:
        return {
            "available": True,
            "provider": "openai",
            "model": model,
            "note": (
                f"GPT correction is on ({model}). Built-in checks still run and are merged."
            ),
        }
    return {
        "available": False,
        "provider": "local",
        "model": None,
        "note": (
            "Built-in academic English checker is on. Set OPENAI_API_KEY on the server "
            "to add GPT corrections for the same tools."
        ),
    }


def tool_catalog() -> dict[str, Any]:
    gpt = gpt_status()
    return {
        "tools": [dict(item) for item in TOOLS],
        "groups": [dict(item) for item in TOOL_GROUPS],
        "categories": list(CATEGORIES),
        "gpt": gpt,
        "engine_note": gpt["note"],
    }


async def review_document(data: bytes, filename: str = "") -> dict[str, Any]:
    paragraphs = paragraphs_from_upload(data, filename)
    if not paragraphs:
        raise ValueError("Could not read text from that file.")
    local = review_local(paragraphs)
    remote, engine = await _openai_review(paragraphs)
    issues = _merge_issues(local, remote)
    issues = _assign_ids(issues)
    note = "Built-in academic English checker."
    if engine == "openai":
        note = "GPT review combined with the built-in checker."
    elif engine and engine.startswith("openai-"):
        note = "GPT was configured but did not complete; showing the built-in checker."
        engine = "local"
    elif not engine:
        engine = "local"
        settings = get_settings()
        if not (getattr(settings, "openai_api_key", None) or "").strip():
            note = (
                "Built-in academic English checker. Set OPENAI_API_KEY on the server "
                "to add GPT suggestions."
            )
    para_payload = []
    for index, text in enumerate(paragraphs):
        ids = [issue["id"] for issue in issues if issue["paragraph_index"] == index]
        para_payload.append({"index": index, "text": text, "issue_ids": ids})
    catalog = tool_catalog()
    return {
        "filename": filename,
        "engine": engine,
        "engine_note": note,
        "gpt": catalog["gpt"],
        "tools": catalog["tools"],
        "groups": catalog["groups"],
        "summary": _summarize(paragraphs, issues),
        "paragraphs": para_payload,
        "issues": issues,
    }
