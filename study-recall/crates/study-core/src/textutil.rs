use unicode_normalization::UnicodeNormalization;

const LATIN_STOP: &[&str] = &[
    "a", "an", "the", "is", "are", "of", "that", "and", "or", "to", "in", "on", "for", "with",
    "by", "from", "as", "it", "this", "these", "those", "be", "was", "were", "into", "their",
    "its", "at", "which", "who", "whom", "while", "during", "than", "then", "also", "can", "may",
    "when", "where", "what", "how", "why", "has", "have", "had", "they", "them", "he", "she",
    "we", "you", "i", "am", "been", "being", "such", "other", "another", "both", "each", "all",
    "any", "if", "so", "but", "about", "do", "does", "did", "not", "no", "nor",
];

const URDU_STOP: &[&str] = &[
    "کا", "کی", "کے", "ہے", "ہیں", "اور", "میں", "سے", "کو", "پر", "ایک", "یہ", "وہ", "کہ", "جو",
    "نے", "ہو", "ہوتا", "ہوتی", "تھا", "تھی", "تھے",
];

const NEGATIONS: &[&str] = &[
    "not", "no", "never", "none", "neither", "nor", "isnt", "arent", "wasnt", "werent", "dont",
    "doesnt", "didnt", "cannot", "cant", "wont", "without", "incorrect", "false", "opposite",
    "نہیں", "نه", "مت",
];

/// Synonym groups for ordinary paraphrase words.
/// Scientific facts are not treated as interchangeable unless the student listed aliases.
const SYNONYM_GROUPS: &[&[&str]] = &[
    &["special", "specializ", "particular"],
    &["transmit", "carry", "convey", "send"],
    &["impulse", "message", "signal"],
    &["nerve", "nervous", "neural"],
    &["maintain", "keep", "preserve"],
    &["electrical", "voltage", "charge"],
    &["relative", "compar", "compared", "compare"],
    &["inside", "interior", "internal"],
    &["outside", "exterior", "external"],
    &["rapid", "quick", "fast"],
    &["change", "shift"],
    &["enter", "enters", "entry"],
    &["leave", "leaves", "exit"],
    &["typically", "usual", "usually", "about"],
    &["consist", "contain", "include", "have"],
    &["cell", "neuron"],
];

pub fn direction_for_language(language: &str) -> &'static str {
    if language == "ur" {
        "rtl"
    } else {
        "ltr"
    }
}

pub fn normalize_language(language: &str) -> Result<&'static str, String> {
    match language.trim().to_ascii_lowercase().as_str() {
        "en" | "english" => Ok("en"),
        "ur" | "urdu" => Ok("ur"),
        "auto" => Ok("auto"),
        _ => Err("Choose English or Urdu.".into()),
    }
}

pub fn normalize_text(input: &str) -> String {
    let nfkc: String = input.nfkc().collect();
    let mut out = String::new();
    for ch in nfkc.chars() {
        if is_arabic_diacritic(ch) || ch == '\u{0640}' {
            continue;
        }
        let mapped = fold_arabic(ch);
        if mapped == '\'' || mapped == '’' {
            continue;
        }
        if mapped.is_alphanumeric() || mapped == '-' {
            out.push(mapped.to_lowercase().next().unwrap_or(mapped));
        } else {
            out.push(' ');
        }
    }
    collapse_ws(&out)
}

fn is_arabic_diacritic(ch: char) -> bool {
    matches!(ch, '\u{064B}'..='\u{065F}' | '\u{0670}' | '\u{06D6}'..='\u{06ED}')
}

fn fold_arabic(ch: char) -> char {
    match ch {
        'أ' | 'إ' | 'آ' | 'ٱ' => 'ا',
        'ى' | 'ي' => 'ی',
        'ك' => 'ک',
        'ة' => 'ہ',
        other => other,
    }
}

fn collapse_ws(input: &str) -> String {
    input.split_whitespace().collect::<Vec<_>>().join(" ")
}

pub fn tokenize(input: &str) -> Vec<String> {
    normalize_text(input)
        .split_whitespace()
        .filter(|t| !t.is_empty())
        .map(|t| t.to_string())
        .collect()
}

pub fn stem(token: &str) -> String {
    if !token.chars().all(|c| c.is_ascii_alphabetic()) {
        return token.to_string();
    }
    let mut t = token.to_string();
    if t.len() > 4 && t.ends_with("ies") {
        t.truncate(t.len() - 3);
        t.push('y');
        return t;
    }
    if t.len() > 5 && (t.ends_with("ing")) {
        t.truncate(t.len() - 3);
        return t;
    }
    if t.len() > 4 && t.ends_with("ed") {
        t.truncate(t.len() - 2);
        return t;
    }
    if t.len() > 3
        && t.ends_with('s')
        && !t.ends_with("ss")
        && !t.ends_with("ous")
        && !t.ends_with("is")
        && !t.ends_with("us")
    {
        t.truncate(t.len() - 1);
    }
    t
}

pub fn tokens_match(a: &str, b: &str) -> bool {
    let sa = stem(a);
    let sb = stem(b);
    if sa == sb {
        return true;
    }
    synonym_id(&sa).is_some() && synonym_id(&sa) == synonym_id(&sb)
}

fn synonym_id(stemmed: &str) -> Option<usize> {
    SYNONYM_GROUPS.iter().position(|group| {
        group.iter().any(|item| stemmed == *item || stemmed.starts_with(item))
    })
}

pub fn is_stopword(token: &str) -> bool {
    LATIN_STOP.contains(&token) || URDU_STOP.contains(&token)
}

pub fn is_negation(token: &str) -> bool {
    NEGATIONS.contains(&token)
}

pub fn content_words(tokens: &[String]) -> Vec<String> {
    tokens
        .iter()
        .filter(|t| !is_stopword(t) && t.chars().any(|c| c.is_alphabetic()))
        .cloned()
        .collect()
}

pub fn is_negated_at(tokens: &[String], index: usize) -> bool {
    let start = index.saturating_sub(4);
    tokens[start..index].iter().any(|t| is_negation(t))
}

/// Case, spacing, punctuation, and Arabic/Urdu letter folding.
pub fn normalize_answer(input: &str) -> String {
    normalize_text(input)
}

pub fn normalize_formula(input: &str) -> String {
    normalize_text(input).replace(' ', "")
}

pub fn sentences(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut cur = String::new();
    for ch in text.chars() {
        cur.push(ch);
        if matches!(ch, '.' | '!' | '?' | '۔') {
            let trimmed = cur.trim().to_string();
            if !trimmed.is_empty() {
                out.push(trimmed);
            }
            cur.clear();
        }
    }
    let trimmed = cur.trim().to_string();
    if !trimmed.is_empty() {
        out.push(trimmed);
    }
    out
}

pub fn word_count(text: &str) -> usize {
    tokenize(text).len()
}

/// Find `term` in `haystack` on a Unicode boundary. Returns byte range into the original string.
pub fn find_term(haystack: &str, term: &str) -> Option<(usize, usize)> {
    let term = term.trim();
    if term.is_empty() {
        return None;
    }
    let hay_l = ascii_lower_keep(haystack);
    let term_l = ascii_lower_keep(term);
    let hay_bytes = hay_l.as_bytes();
    let term_bytes = term_l.as_bytes();
    if term_bytes.len() > hay_bytes.len() {
        return None;
    }
    let mut i = 0;
    while i + term_bytes.len() <= hay_bytes.len() {
        if !hay_l.is_char_boundary(i) {
            i += 1;
            continue;
        }
        let end = i + term_bytes.len();
        if !hay_l.is_char_boundary(end) {
            i += 1;
            continue;
        }
        if &hay_bytes[i..end] == term_bytes && boundary_ok(&hay_l, i, end) {
            return Some((i, end));
        }
        i += 1;
    }
    None
}

fn ascii_lower_keep(input: &str) -> String {
    input
        .chars()
        .map(|c| {
            if c.is_ascii_uppercase() {
                c.to_ascii_lowercase()
            } else {
                c
            }
        })
        .collect()
}

fn boundary_ok(hay: &str, start: usize, end: usize) -> bool {
    let before_ok = start == 0
        || hay[..start]
            .chars()
            .next_back()
            .map(|c| !c.is_alphanumeric())
            .unwrap_or(true);
    let after_ok = end == hay.len()
        || hay[end..]
            .chars()
            .next()
            .map(|c| !c.is_alphanumeric())
            .unwrap_or(true);
    before_ok && after_ok
}

pub fn damerau_distance(a: &str, b: &str) -> usize {
    damerau_precise(&a.chars().collect::<Vec<_>>(), &b.chars().collect::<Vec<_>>())
}

fn damerau_precise(a: &[char], b: &[char]) -> usize {
    let n = a.len();
    let m = b.len();
    let mut d = vec![vec![0usize; m + 1]; n + 1];
    for i in 0..=n {
        d[i][0] = i;
    }
    for j in 0..=m {
        d[0][j] = j;
    }
    for i in 1..=n {
        for j in 1..=m {
            let cost = if a[i - 1] == b[j - 1] { 0 } else { 1 };
            d[i][j] = (d[i - 1][j] + 1)
                .min(d[i][j - 1] + 1)
                .min(d[i - 1][j - 1] + cost);
            if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                d[i][j] = d[i][j].min(d[i - 2][j - 2] + 1);
            }
        }
    }
    d[n][m]
}

pub fn spelling_variant(expected: &str, given: &str) -> bool {
    if expected.chars().any(|c| !c.is_ascii_alphabetic())
        || given.chars().any(|c| !c.is_ascii_alphabetic())
    {
        return false;
    }
    if expected.len() < 7 || given.len() < 7 {
        return false;
    }
    if expected.chars().next() != given.chars().next() {
        return false;
    }
    damerau_precise(
        &expected.chars().collect::<Vec<_>>(),
        &given.chars().collect::<Vec<_>>(),
    ) == 1
}

pub fn like_pattern(query: &str) -> String {
    let escaped = query
        .replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_");
    format!("%{escaped}%")
}

pub fn combine_transcripts(parts: &[impl AsRef<str>]) -> String {
    parts
        .iter()
        .map(|p| p.as_ref().trim())
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn folds_urdu_and_latin_without_dropping_letters() {
        let urdu = normalize_text("نیوران  ایک   خلیہ ہے");
        assert!(urdu.contains("نیوران"));
        assert!(!urdu.contains("  "));
        assert_eq!(normalize_text("Axon!"), "axon");
        assert_eq!(direction_for_language("ur"), "rtl");
        assert_eq!(direction_for_language("en"), "ltr");
    }

    #[test]
    fn stems_plurals_without_damaging_ous_words() {
        assert_eq!(stem("impulses"), "impulse");
        assert_eq!(stem("nervous"), "nervous");
        assert_eq!(stem("transmits"), "transmit");
        assert!(tokens_match("specialized", "special"));
        assert!(tokens_match("carry", "transmits"));
        assert!(tokens_match("messages", "impulses"));
    }

    #[test]
    fn finds_axon_on_a_word_boundary() {
        let sentence = "A neuron consists of a cell body, dendrites, and an axon.";
        let (start, end) = find_term(sentence, "axon").unwrap();
        assert_eq!(&sentence[start..end], "axon");
        assert!(find_term(sentence, "on").is_none());
    }

    #[test]
    fn spelling_tolerance_is_conservative() {
        assert!(spelling_variant("potential", "potenial"));
        assert!(!spelling_variant("axon", "axan"));
        assert!(!spelling_variant("dendrite", "axon"));
        assert!(!spelling_variant("نیوران", "نیورون"));
    }
}
