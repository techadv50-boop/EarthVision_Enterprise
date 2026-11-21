use serde::{Deserialize, Serialize};

use crate::textutil::{
    content_words, is_negated_at, normalize_answer, normalize_formula, spelling_variant, stem,
    tokenize, tokens_match,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConceptRef {
    pub kind: String,
    pub label: String,
    pub content: String,
    pub aliases: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConceptGrade {
    pub essential: f64,
    pub factual: f64,
    pub supporting: f64,
    pub covered: Vec<String>,
    pub missing: Vec<String>,
    pub incorrect: Vec<String>,
    pub reasons: Vec<String>,
    /// `approximate` or `review`
    pub confidence: String,
    pub method: String,
}

impl ConceptGrade {
    pub fn weighted(&self, essential_w: f64, factual_w: f64, support_w: f64) -> Option<f64> {
        if self.confidence == "review" {
            return None;
        }
        let mut score = essential_w * self.essential
            + factual_w * self.factual
            + support_w * self.supporting;
        let total = (self.covered.len() + self.missing.len() + self.incorrect.len()).max(1);
        if !self.incorrect.is_empty() {
            let ratio = self.incorrect.len() as f64 / total as f64;
            if ratio >= 0.25 {
                score = score.min(0.49);
                self_reason_cap(&mut score);
            } else {
                score = score.min(0.9);
            }
        }
        Some(score.clamp(0.0, 1.0))
    }
}

fn self_reason_cap(_score: &mut f64) {}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ItemGrade {
    pub awarded: Option<f64>,
    pub max_marks: f64,
    pub method: String,
    pub confidence: String,
    pub explanation: String,
    pub covered: Vec<String>,
    pub missing: Vec<String>,
    pub incorrect: Vec<String>,
}

struct Item {
    label: String,
    strict: bool,
}

pub fn grade_recall(reference: &str, answer: &str, concepts: &[ConceptRef]) -> ConceptGrade {
    let answer_tokens = tokenize(answer);
    let reference_tokens = tokenize(reference);
    if answer_tokens.is_empty() {
        let missing = essential_labels(reference, concepts);
        return ConceptGrade {
            essential: 0.0,
            factual: 0.0,
            supporting: 0.0,
            covered: vec![],
            missing,
            incorrect: vec![],
            reasons: vec!["No answer was submitted.".into()],
            confidence: "approximate".into(),
            method: "approximate-concept-rubric".into(),
        };
    }

    let items = essential_items(reference, concepts);
    if items.is_empty() {
        return ConceptGrade {
            essential: 0.0,
            factual: 0.0,
            supporting: 0.0,
            covered: vec![],
            missing: vec![],
            incorrect: vec![],
            reasons: vec![
                "This topic has no reference text or key points to grade against. Add notes before treating a score as meaningful."
                    .into(),
            ],
            confidence: "review".into(),
            method: "review-required".into(),
        };
    }

    let mut covered = Vec::new();
    let mut missing = Vec::new();
    let mut incorrect = Vec::new();
    for item in &items {
        match match_item(item, &answer_tokens) {
            ItemMatch::Covered => covered.push(item.label.clone()),
            ItemMatch::Missing => missing.push(item.label.clone()),
            ItemMatch::Contradicted => incorrect.push(item.label.clone()),
        }
    }
    let total = items.len() as f64;
    let essential = covered.len() as f64 / total;
    let factual = if incorrect.is_empty() {
        if essential >= 0.5 {
            1.0
        } else {
            0.55 + 0.45 * essential
        }
    } else {
        let ratio = incorrect.len() as f64 / total;
        (1.0 - ratio).clamp(0.0, 0.4)
    };
    let supporting = supporting_score(reference, concepts, &reference_tokens, &answer_tokens, essential);
    let mut reasons = Vec::new();
    if !covered.is_empty() {
        reasons.push(format!("Covered: {}.", covered.join("; ")));
    }
    if !missing.is_empty() {
        reasons.push(format!("Missing: {}.", missing.join("; ")));
    }
    if !incorrect.is_empty() {
        reasons.push(format!(
            "Contradicted or negated: {}.",
            incorrect.join("; ")
        ));
    }
    reasons.push(
        "Approximate score. A local language model is not configured, so wording was compared by concepts, aliases, and ordinary paraphrases rather than by an AI grader."
            .into(),
    );
    ConceptGrade {
        essential,
        factual,
        supporting,
        covered,
        missing,
        incorrect,
        reasons,
        confidence: "approximate".into(),
        method: "approximate-concept-rubric".into(),
    }
}

enum ItemMatch {
    Covered,
    Missing,
    Contradicted,
}

fn match_item(item: &Item, answer_tokens: &[String]) -> ItemMatch {
    if item.strict {
        let needle = normalize_formula(&item.label);
        let hay = normalize_formula(&answer_tokens.join(" "));
        return if !needle.is_empty() && hay.contains(&needle) {
            ItemMatch::Covered
        } else {
            ItemMatch::Missing
        };
    }
    let concept_tokens = tokenize(&item.label);
    let words = content_words(&concept_tokens);
    if words.is_empty() {
        return ItemMatch::Missing;
    }
    let mut clean = 0usize;
    let mut negated = 0usize;
    for word in &words {
        match polarity(answer_tokens, word) {
            Some(true) => negated += 1,
            Some(false) => clean += 1,
            None => {}
        }
    }
    let concept_negated = words.iter().any(|word| {
        polarity(&concept_tokens, word) == Some(true)
    });
    if negated > 0 && !concept_negated && (words.len() == 1 || negated * 2 >= words.len() || clean == 0)
    {
        return ItemMatch::Contradicted;
    }
    // A multi-word point is contradicted when a matched predicate is negated.
    if negated > 0 && !concept_negated && clean * 2 < words.len() {
        return ItemMatch::Contradicted;
    }
    let hits = clean;
    let needed = if words.len() == 1 {
        1
    } else {
        ((words.len() * 3) + 4) / 5 // ceil 60%
    };
    if hits >= needed && negated == 0 {
        ItemMatch::Covered
    } else if negated > 0 && !concept_negated {
        ItemMatch::Contradicted
    } else {
        ItemMatch::Missing
    }
}

/// Some(true) when a matching token is negated, Some(false) when it is affirmed.
fn polarity(tokens: &[String], word: &str) -> Option<bool> {
    for (index, token) in tokens.iter().enumerate() {
        if tokens_match(token, word) {
            return Some(is_negated_at(tokens, index));
        }
    }
    None
}

fn essential_items(reference: &str, concepts: &[ConceptRef]) -> Vec<Item> {
    let mut items = Vec::new();
    for concept in concepts {
        if concept.kind == "example" {
            continue;
        }
        let strict = concept.kind == "formula";
        let text = if concept.kind == "keyword" || concept.kind == "formula" {
            concept.content.trim().to_string()
        } else if !concept.label.trim().is_empty() && concept.kind == "definition" {
            format!("{}: {}", concept.label.trim(), concept.content.trim())
        } else {
            concept.content.trim().to_string()
        };
        if text.is_empty() {
            continue;
        }
        items.push(Item {
            label: text,
            strict,
        });
        for alias in split_aliases(&concept.aliases) {
            items.push(Item {
                label: alias,
                strict,
            });
        }
    }
    if items.is_empty() {
        let tokens = tokenize(reference);
        let mut words = content_words(&tokens);
        words.sort_by_key(|w| std::cmp::Reverse(w.chars().count()));
        words.dedup();
        for word in words.into_iter().take(12) {
            items.push(Item {
                label: word,
                strict: false,
            });
        }
    }
    items
}

fn essential_labels(reference: &str, concepts: &[ConceptRef]) -> Vec<String> {
    essential_items(reference, concepts)
        .into_iter()
        .map(|i| i.label)
        .collect()
}

fn split_aliases(aliases: &str) -> Vec<String> {
    aliases
        .split([',', ';', '|'])
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn supporting_score(
    _reference: &str,
    concepts: &[ConceptRef],
    reference_tokens: &[String],
    answer_tokens: &[String],
    essential: f64,
) -> f64 {
    if concepts.is_empty() {
        return essential;
    }
    let mut used = Vec::new();
    for concept in concepts {
        used.extend(content_words(&tokenize(&concept.content)));
        used.extend(content_words(&tokenize(&concept.label)));
    }
    let extras: Vec<String> = content_words(reference_tokens)
        .into_iter()
        .filter(|word| !used.iter().any(|u| tokens_match(u, word)))
        .collect();
    if extras.is_empty() {
        return if essential >= 0.999 { 1.0 } else { essential };
    }
    let hit = extras
        .iter()
        .filter(|word| polarity(answer_tokens, word) == Some(false))
        .count();
    hit as f64 / extras.len() as f64
}

pub fn apply_model_grade(base: ConceptGrade, model: ConceptGrade) -> ConceptGrade {
    let mut grade = model;
    grade.method = "local-llama".into();
    grade.confidence = "model-estimated".into();
    grade.reasons.insert(
        0,
        "Estimated by a local language model. This is not an infallible mark.".into(),
    );
    if grade.covered.is_empty() && grade.missing.is_empty() {
        grade.covered = base.covered;
        grade.missing = base.missing;
        grade.incorrect = base.incorrect;
    }
    grade
}

pub fn parse_model_grade(output: &str) -> Option<ConceptGrade> {
    let start = output.find('{')?;
    let end = output.rfind('}')?;
    if end <= start {
        return None;
    }
    let value: serde_json::Value = serde_json::from_str(&output[start..=end]).ok()?;
    let essential = value.get("essential")?.as_f64()?;
    let factual = value.get("factual")?.as_f64()?;
    let supporting = value.get("supporting")?.as_f64()?;
    if !(0.0..=1.0).contains(&essential)
        || !(0.0..=1.0).contains(&factual)
        || !(0.0..=1.0).contains(&supporting)
    {
        return None;
    }
    let strings = |key: &str| {
        value
            .get(key)
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default()
    };
    Some(ConceptGrade {
        essential,
        factual,
        supporting,
        covered: strings("covered"),
        missing: strings("missing"),
        incorrect: strings("incorrect"),
        reasons: vec!["Parsed from local model output.".into()],
        confidence: "model-estimated".into(),
        method: "local-llama".into(),
    })
}

pub fn grade_mcq(selected: Option<&str>, correct: &str, max_marks: f64) -> ItemGrade {
    let selected_norm = selected.unwrap_or("").trim().to_ascii_uppercase();
    let correct_norm = correct.trim().to_ascii_uppercase();
    let ok = !selected_norm.is_empty() && selected_norm == correct_norm;
    ItemGrade {
        awarded: Some(if ok { max_marks } else { 0.0 }),
        max_marks,
        method: "exact-match".into(),
        confidence: "exact".into(),
        explanation: if selected.unwrap_or("").trim().is_empty() {
            "Unanswered. No marks awarded.".into()
        } else if ok {
            format!("Selected {correct_norm}, which is the saved correct option.")
        } else {
            format!("Selected {selected_norm}. The saved correct option is {correct_norm}.")
        },
        covered: vec![],
        missing: vec![],
        incorrect: vec![],
    }
}

pub fn grade_fib(
    response: &str,
    correct: &str,
    alternatives: &[String],
    confusion_terms: &[String],
    max_marks: f64,
) -> ItemGrade {
    let response_n = normalize_answer(response);
    if response_n.is_empty() {
        return ItemGrade {
            awarded: Some(0.0),
            max_marks,
            method: "exact-match".into(),
            confidence: "exact".into(),
            explanation: "Unanswered. No marks awarded.".into(),
            covered: vec![],
            missing: vec![correct.to_string()],
            incorrect: vec![],
        };
    }
    let accepted: Vec<String> = std::iter::once(correct.to_string())
        .chain(alternatives.iter().cloned())
        .collect();
    for candidate in &accepted {
        if answers_equal(&response_n, candidate) {
            return ItemGrade {
                awarded: Some(max_marks),
                max_marks,
                method: "exact-match".into(),
                confidence: "exact".into(),
                explanation: format!("Matches the saved answer \"{candidate}\"."),
                covered: vec![candidate.clone()],
                missing: vec![],
                incorrect: vec![],
            };
        }
    }
    let fuzzy = accepted.iter().any(|candidate| {
        let norm = normalize_answer(candidate);
        spelling_variant(&norm, &response_n)
            && !confusion_terms.iter().any(|term| {
                let term_n = normalize_answer(term);
                term_n != norm && (term_n == response_n || spelling_variant(&term_n, &response_n))
            })
    });
    if fuzzy {
        return ItemGrade {
            awarded: Some(max_marks),
            max_marks,
            method: "spelling-tolerant".into(),
            confidence: "exact".into(),
            explanation: "Accepted as a spelling variant that does not match a different saved term."
                .into(),
            covered: vec![correct.to_string()],
            missing: vec![],
            incorrect: vec![],
        };
    }
    ItemGrade {
        awarded: Some(0.0),
        max_marks,
        method: "exact-match".into(),
        confidence: "exact".into(),
        explanation: format!(
            "\"{response}\" does not match the saved answer \"{correct}\". Spelling tolerance was not applied because the difference can change the meaning."
        ),
        covered: vec![],
        missing: vec![correct.to_string()],
        incorrect: vec![response.trim().to_string()],
    }
}

fn answers_equal(response_n: &str, candidate: &str) -> bool {
    let norm = normalize_answer(candidate);
    if response_n == norm {
        return true;
    }
    let rs = stem(response_n);
    let cs = stem(&norm);
    rs == cs && !rs.is_empty()
}

pub fn grade_descriptive(
    reference: &str,
    answer: &str,
    concepts: &[ConceptRef],
    max_marks: f64,
    model: Option<ConceptGrade>,
) -> ItemGrade {
    let rubric = grade_recall(reference, answer, concepts);
    let grade = if let Some(model) = model {
        apply_model_grade(rubric, model)
    } else {
        rubric
    };
    if grade.confidence == "review" {
        return ItemGrade {
            awarded: None,
            max_marks,
            method: grade.method,
            confidence: "review".into(),
            explanation: grade.reasons.join(" "),
            covered: grade.covered,
            missing: grade.missing,
            incorrect: grade.incorrect,
        };
    }
    let ratio = grade.weighted(0.40, 0.40, 0.20).unwrap_or(0.0);
    let raw = max_marks * ratio;
    let awarded = ((raw * 2.0).round() / 2.0).clamp(0.0, max_marks);
    let mut explanation = grade.reasons.join(" ");
    explanation.push_str(&format!(
        " Factual correctness {:.0}%, concept coverage {:.0}%, completeness {:.0}%. Estimated mark {awarded} of {max_marks}.",
        grade.factual * 100.0,
        grade.essential * 100.0,
        grade.supporting * 100.0
    ));
    ItemGrade {
        awarded: Some(awarded),
        max_marks,
        method: grade.method,
        confidence: grade.confidence,
        explanation,
        covered: grade.covered,
        missing: grade.missing,
        incorrect: grade.incorrect,
    }
}

pub fn oral_percent(grade: &ConceptGrade) -> Option<f64> {
    grade
        .weighted(0.50, 0.30, 0.20)
        .map(|score| (score * 1000.0).round() / 10.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn neuron_reference() -> &'static str {
        "A neuron is a specialized cell that transmits nerve impulses."
    }

    #[test]
    fn paraphrase_scores_as_substantially_correct() {
        let grade = grade_recall(
            neuron_reference(),
            "Neurons are special cells that carry messages through the nervous system.",
            &[],
        );
        let score = oral_percent(&grade).unwrap();
        assert!(
            score >= 80.0,
            "expected a high recall score, got {score} covered={:?} missing={:?} bad={:?}",
            grade.covered, grade.missing, grade.incorrect
        );
        assert!(grade.incorrect.is_empty());
        assert_eq!(grade.method, "approximate-concept-rubric");
        assert_eq!(grade.confidence, "approximate");
    }

    #[test]
    fn keyword_overlap_with_a_wrong_statement_is_not_full_marks() {
        let grade = grade_recall(
            neuron_reference(),
            "A neuron is a type of bone that stores calcium.",
            &[],
        );
        let score = oral_percent(&grade).unwrap();
        assert!(score < 50.0, "score {score}");
    }

    #[test]
    fn negated_science_is_not_accepted() {
        let grade = grade_recall(
            neuron_reference(),
            "Neurons are special cells that do not carry messages through the nervous system.",
            &[],
        );
        let score = oral_percent(&grade).unwrap();
        assert!(!grade.incorrect.is_empty(), "{:?}", grade);
        assert!(score <= 49.0, "score {score}");
    }

    #[test]
    fn empty_reference_requires_review() {
        let grade = grade_recall("", "something", &[]);
        assert_eq!(grade.confidence, "review");
        assert!(oral_percent(&grade).is_none());
    }

    #[test]
    fn fib_accepts_case_and_plural_and_rejects_a_different_term() {
        let ok = grade_fib("  AXONS ", "axon", &[], &[], 3.0);
        assert_eq!(ok.awarded, Some(3.0));
        let wrong = grade_fib("dendrite", "axon", &[], &["dendrite".into()], 3.0);
        assert_eq!(wrong.awarded, Some(0.0));
        let urdu = grade_fib("نیوران", "نیوران", &[], &[], 3.0);
        assert_eq!(urdu.awarded, Some(3.0));
        let urdu_wrong = grade_fib("خلیہ", "نیوران", &[], &[], 3.0);
        assert_eq!(urdu_wrong.awarded, Some(0.0));
    }

    #[test]
    fn mcq_marks_only_the_saved_option() {
        assert_eq!(grade_mcq(Some("b"), "B", 2.0).awarded, Some(2.0));
        assert_eq!(grade_mcq(Some("A"), "B", 2.0).awarded, Some(0.0));
        assert_eq!(grade_mcq(None, "B", 2.0).awarded, Some(0.0));
    }

    #[test]
    fn model_output_parses_and_garbage_does_not() {
        let raw = "Sure\n{\"essential\":0.8,\"factual\":0.7,\"supporting\":0.6,\"covered\":[\"cell\"],\"missing\":[],\"incorrect\":[]}";
        let parsed = parse_model_grade(raw).unwrap();
        assert_eq!(parsed.essential, 0.8);
        assert!(parse_model_grade("no json here").is_none());
        assert!(parse_model_grade("{\"essential\":2,\"factual\":0,\"supporting\":0}").is_none());
    }
}
