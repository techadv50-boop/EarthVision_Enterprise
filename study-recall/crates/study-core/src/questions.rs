use rand::rngs::StdRng;
use rand::{Rng, SeedableRng};
use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::grading::ConceptRef;
use crate::textutil::{content_words, find_term, is_stopword, sentences, tokenize, word_count};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TopicMaterial {
    pub id: String,
    pub title: String,
    pub reference_text: String,
    pub language: String,
    pub concepts: Vec<ConceptRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct McqOption {
    pub id: String,
    pub text: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExamQuestion {
    pub question_type: String,
    pub prompt: String,
    pub options: Vec<McqOption>,
    pub correct_answer: String,
    pub alternatives: Vec<String>,
    pub rubric_points: Vec<String>,
    pub topic_ids: Vec<String>,
    pub max_marks: i64,
    pub source_topic_id: String,
    pub source_passage: String,
    pub difficulty: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PaperOffer {
    pub size_id: String,
    pub title: String,
    pub feasible: bool,
    pub reason: String,
    pub fib_count: usize,
    pub mcq_count: usize,
    pub short_count: usize,
    pub long_count: usize,
    pub total_marks: i64,
    pub section_a_marks: i64,
    pub section_b_marks: i64,
    pub section_c_marks: i64,
    pub percent_a: f64,
    pub percent_b: f64,
    pub percent_c: f64,
    pub rounding_note: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Proposal {
    pub offers: Vec<PaperOffer>,
    pub fib_available: usize,
    pub mcq_available: usize,
    pub short_available: usize,
    pub long_available: usize,
    pub difficulty_note: String,
    pub material_note: String,
}

#[derive(Debug, Clone)]
struct Draft {
    question_type: String,
    prompt: String,
    options: Vec<McqOption>,
    correct_answer: String,
    alternatives: Vec<String>,
    rubric_points: Vec<String>,
    topic_ids: Vec<String>,
    source_topic_id: String,
    source_passage: String,
    difficulty: String,
}

struct Pool {
    fib: Vec<Draft>,
    mcq: Vec<Draft>,
    short_q: Vec<Draft>,
    long_q: Vec<Draft>,
    difficulty_note: String,
}

struct Shape {
    id: &'static str,
    title: &'static str,
    fib: usize,
    mcq: usize,
    short_q: usize,
    long_q: usize,
    fib_each: i64,
    mcq_each: i64,
    short_each: i64,
    long_each: i64,
    extra: &'static str,
}

pub fn propose(topics: &[TopicMaterial], difficulty: &str) -> Proposal {
    let pool = build_pool(topics, difficulty);
    let shapes = shapes();
    let mut offers = Vec::new();
    for shape in &shapes {
        offers.push(offer_from_shape(shape, &pool));
    }
    if !offers.iter().any(|o| o.feasible) {
        if let Some(custom) = custom_offer(&pool) {
            offers.push(custom);
        }
    }
    let material_note = if pool.fib.is_empty()
        && pool.mcq.is_empty()
        && pool.short_q.is_empty()
        && pool.long_q.is_empty()
    {
        "No questions could be supported by the saved notes. Add reference text, definitions, facts, or keywords to the selected topics, then try again.".into()
    } else {
        "Questions are prepared only from the chapters you selected. Nothing is added that is not supported by those notes.".into()
    };
    Proposal {
        offers,
        fib_available: pool.fib.len(),
        mcq_available: pool.mcq.len(),
        short_available: pool.short_q.len(),
        long_available: pool.long_q.len(),
        difficulty_note: pool.difficulty_note,
        material_note,
    }
}

pub fn build_paper(
    topics: &[TopicMaterial],
    difficulty: &str,
    size_id: &str,
    seed: u64,
) -> AppResult<(PaperOffer, Vec<ExamQuestion>)> {
    let mut pool = build_pool(topics, difficulty);
    let mut rng = StdRng::seed_from_u64(seed);
    shuffle(&mut pool.fib, &mut rng);
    shuffle(&mut pool.mcq, &mut rng);
    shuffle(&mut pool.short_q, &mut rng);
    shuffle(&mut pool.long_q, &mut rng);
    let proposal = propose(topics, difficulty);
    let offer = proposal
        .offers
        .into_iter()
        .find(|o| o.size_id == size_id && o.feasible)
        .ok_or_else(|| {
            AppError::Invalid(
                "That paper size is not available for the selected notes. Choose one of the listed papers."
                    .into(),
            )
        })?;
    let shape_marks = marks_for(&offer);
    let mut questions = Vec::new();
    push_section(
        &mut questions,
        &pool.fib,
        offer.fib_count,
        &shape_marks.0,
        &mut rng,
    );
    push_section(
        &mut questions,
        &pool.mcq,
        offer.mcq_count,
        &shape_marks.1,
        &mut rng,
    );
    push_section(
        &mut questions,
        &pool.short_q,
        offer.short_count,
        &shape_marks.2,
        &mut rng,
    );
    push_section(
        &mut questions,
        &pool.long_q,
        offer.long_count,
        &shape_marks.3,
        &mut rng,
    );
    if questions.len()
        != offer.fib_count + offer.mcq_count + offer.short_count + offer.long_count
    {
        return Err(AppError::Invalid(
            "The paper could not be filled without repeating unsupported questions.".into(),
        ));
    }
    let total: i64 = questions.iter().map(|q| q.max_marks).sum();
    if total != offer.total_marks {
        return Err(AppError::Invalid(format!(
            "Internal mark allocation mismatch ({total} vs {}).",
            offer.total_marks
        )));
    }
    for question in &questions {
        validate_question(question)?;
    }
    Ok((offer, questions))
}

fn push_section(
    out: &mut Vec<ExamQuestion>,
    drafts: &[Draft],
    count: usize,
    marks: &[i64],
    rng: &mut StdRng,
) {
    for (draft, &max_marks) in drafts.iter().take(count).zip(marks.iter()) {
        let mut question = draft.clone();
        if question.question_type == "mcq" {
            assign_mcq_letters(&mut question, rng);
        }
        out.push(ExamQuestion {
            question_type: question.question_type,
            prompt: question.prompt,
            options: question.options,
            correct_answer: question.correct_answer,
            alternatives: question.alternatives,
            rubric_points: question.rubric_points,
            topic_ids: question.topic_ids,
            max_marks,
            source_topic_id: question.source_topic_id,
            source_passage: question.source_passage,
            difficulty: question.difficulty,
        });
    }
}

fn assign_mcq_letters(draft: &mut Draft, rng: &mut StdRng) {
    let correct_text = draft
        .options
        .iter()
        .find(|o| o.id == draft.correct_answer)
        .map(|o| o.text.clone())
        .unwrap_or_else(|| draft.correct_answer.clone());
    let mut texts: Vec<String> = draft.options.iter().map(|o| o.text.clone()).collect();
    if texts.len() != 4 {
        return;
    }
    shuffle(&mut texts, rng);
    let letters = ["A", "B", "C", "D"];
    draft.options = texts
        .into_iter()
        .enumerate()
        .map(|(i, text)| McqOption {
            id: letters[i].to_string(),
            text,
        })
        .collect();
    draft.correct_answer = draft
        .options
        .iter()
        .find(|o| o.text == correct_text)
        .map(|o| o.id.clone())
        .unwrap_or_else(|| "A".into());
}

fn marks_for(offer: &PaperOffer) -> (Vec<i64>, Vec<i64>, Vec<i64>, Vec<i64>) {
    if let Some(shape) = shapes().into_iter().find(|s| s.id == offer.size_id) {
        return (
            vec![shape.fib_each; shape.fib],
            vec![shape.mcq_each; shape.mcq],
            vec![shape.short_each; shape.short_q],
            vec![shape.long_each; shape.long_q],
        );
    }
    let (short_marks, long_marks) =
        split_section_c(offer.section_c_marks, offer.short_count, offer.long_count);
    (
        split_marks(offer.section_a_marks, offer.fib_count),
        split_marks(offer.section_b_marks, offer.mcq_count),
        short_marks,
        long_marks,
    )
}

fn offer_from_shape(shape: &Shape, pool: &Pool) -> PaperOffer {
    let feasible = pool.fib.len() >= shape.fib
        && pool.mcq.len() >= shape.mcq
        && pool.short_q.len() >= shape.short_q
        && pool.long_q.len() >= shape.long_q
        && shape.fib + shape.mcq + shape.short_q + shape.long_q > 0;
    let section_a = shape.fib as i64 * shape.fib_each;
    let section_b = shape.mcq as i64 * shape.mcq_each;
    let section_c = shape.short_q as i64 * shape.short_each + shape.long_q as i64 * shape.long_each;
    let total = section_a + section_b + section_c;
    let reason = if feasible {
        "This paper can be built from the selected notes.".into()
    } else {
        format!(
            "This paper needs {} fill-in-the-blank, {} multiple-choice, {} short, and {} long questions. The selected notes can support {}, {}, {}, and {}.",
            shape.fib, shape.mcq, shape.short_q, shape.long_q,
            pool.fib.len(), pool.mcq.len(), pool.short_q.len(), pool.long_q.len()
        )
    };
    percentages(shape.id, shape.title, feasible, reason, shape.fib, shape.mcq, shape.short_q, shape.long_q, section_a, section_b, section_c, total, shape.extra)
}

fn custom_offer(pool: &Pool) -> Option<PaperOffer> {
    let fib = pool.fib.len().min(10);
    let mcq = pool.mcq.len().min(20);
    let short_q = pool.short_q.len().min(6);
    let long_q = pool.long_q.len().min(1);
    if fib + mcq + short_q + long_q == 0 {
        return None;
    }
    let mut weights = [0i64, 0, 0];
    if fib > 0 {
        weights[0] = 30;
    }
    if mcq > 0 {
        weights[1] = 40;
    }
    if short_q + long_q > 0 {
        weights[2] = 30;
    }
    let natural = fib as i64 * 3 + mcq as i64 * 2 + short_q as i64 * 5 + long_q as i64 * 15;
    let total = natural.max(1);
    let sections = section_marks(total, weights);
    let extra = "This is a smaller paper because the notes did not support a standard preset. Empty sections are omitted.";
    Some(percentages(
        "custom",
        "Smaller paper from the available notes",
        true,
        "Built from the questions the selected notes can support.".into(),
        fib,
        mcq,
        short_q,
        long_q,
        sections[0],
        sections[1],
        sections[2],
        total,
        extra,
    ))
}

fn percentages(
    id: &str,
    title: &str,
    feasible: bool,
    reason: String,
    fib: usize,
    mcq: usize,
    short_q: usize,
    long_q: usize,
    section_a: i64,
    section_b: i64,
    section_c: i64,
    total: i64,
    extra: &str,
) -> PaperOffer {
    let percent_a = percent(section_a, total);
    let percent_b = percent(section_b, total);
    let percent_c = percent(section_c, total);
    let exact = (percent_a - 30.0).abs() < 0.051
        && (percent_b - 40.0).abs() < 0.051
        && (percent_c - 30.0).abs() < 0.051;
    let rounding_note = if exact {
        format!(
            "Section A {section_a} marks (30%), Section B {section_b} marks (40%), Section C {section_c} marks (30%). {extra}"
        )
    } else {
        format!(
            "Section A {section_a} marks ({percent_a:.1}%), Section B {section_b} marks ({percent_b:.1}%), Section C {section_c} marks ({percent_c:.1}%). The 30/40/30 target could not be met exactly with these questions. {extra}"
        )
    };
    PaperOffer {
        size_id: id.into(),
        title: title.into(),
        feasible,
        reason,
        fib_count: fib,
        mcq_count: mcq,
        short_count: short_q,
        long_count: long_q,
        total_marks: total,
        section_a_marks: section_a,
        section_b_marks: section_b,
        section_c_marks: section_c,
        percent_a,
        percent_b,
        percent_c,
        rounding_note,
    }
}

pub fn section_marks(total: i64, weights: [i64; 3]) -> [i64; 3] {
    let wsum = weights.iter().sum::<i64>().max(1);
    let exact: Vec<f64> = weights
        .iter()
        .map(|w| total as f64 * (*w as f64) / wsum as f64)
        .collect();
    let mut floors: Vec<i64> = exact.iter().map(|v| v.floor() as i64).collect();
    let mut rem = total - floors.iter().sum::<i64>();
    let mut order: Vec<usize> = (0..weights.len()).collect();
    order.sort_by(|&a, &b| {
        let fa = exact[a] - floors[a] as f64;
        let fb = exact[b] - floors[b] as f64;
        fb.partial_cmp(&fa)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });
    let mut cursor = 0;
    while rem > 0 && !order.is_empty() {
        floors[order[cursor % order.len()]] += 1;
        rem -= 1;
        cursor += 1;
    }
    [floors[0], floors[1], floors[2]]
}

pub fn split_marks(total: i64, count: usize) -> Vec<i64> {
    if count == 0 {
        return Vec::new();
    }
    let base = total / count as i64;
    let mut rem = total % count as i64;
    let mut marks = vec![base; count];
    for mark in &mut marks {
        if rem > 0 {
            *mark += 1;
            rem -= 1;
        }
    }
    marks
}

fn split_section_c(total: i64, short_n: usize, long_n: usize) -> (Vec<i64>, Vec<i64>) {
    if long_n == 0 {
        return (split_marks(total, short_n), Vec::new());
    }
    if short_n == 0 {
        return (Vec::new(), split_marks(total, long_n));
    }
    let long_total = total / 2;
    let short_total = total - long_total;
    (
        split_marks(short_total, short_n),
        split_marks(long_total, long_n),
    )
}

fn percent(part: i64, total: i64) -> f64 {
    if total <= 0 {
        0.0
    } else {
        (part as f64 * 1000.0 / total as f64).round() / 10.0
    }
}

fn shapes() -> Vec<Shape> {
    vec![
        Shape { id: "full", title: "Full paper (100 marks)", fib: 10, mcq: 20, short_q: 3, long_q: 1, fib_each: 3, mcq_each: 2, short_each: 5, long_each: 15, extra: "Short questions are 15 marks and the long question is 15 marks." },
        Shape { id: "full-short-only", title: "Full paper without a long question (100 marks)", fib: 10, mcq: 20, short_q: 6, long_q: 0, fib_each: 3, mcq_each: 2, short_each: 5, long_each: 0, extra: "Section C is six short questions because a separate long question was not requested for this preset." },
        Shape { id: "half", title: "Half paper (50 marks)", fib: 5, mcq: 10, short_q: 2, long_q: 1, fib_each: 3, mcq_each: 2, short_each: 5, long_each: 5, extra: "The long question is 5 marks so Section C stays at 15 marks." },
        Shape { id: "half-short-only", title: "Half paper without a long question (50 marks)", fib: 5, mcq: 10, short_q: 3, long_q: 0, fib_each: 3, mcq_each: 2, short_each: 5, long_each: 0, extra: "Section C is three short questions." },
        Shape { id: "brief", title: "Brief paper (20 marks)", fib: 3, mcq: 4, short_q: 1, long_q: 1, fib_each: 2, mcq_each: 2, short_each: 3, long_each: 3, extra: "A brief paper keeps the same 30/40/30 balance." },
        Shape { id: "brief-short-only", title: "Brief paper without a long question (20 marks)", fib: 3, mcq: 4, short_q: 2, long_q: 0, fib_each: 2, mcq_each: 2, short_each: 3, long_each: 0, extra: "Section C is two short questions." },
    ]
}

fn build_pool(topics: &[TopicMaterial], difficulty: &str) -> Pool {
    let mut fib = Vec::new();
    let mut downgraded = false;
    for topic in topics {
        let mut made = 0;
        for draft in fib_for_topic(topic, difficulty, &mut downgraded) {
            if validate_draft(&draft) {
                fib.push(draft);
                made += 1;
            }
            if made == 3 {
                break;
            }
        }
    }
    let mcq = mcq_for_topics(topics, difficulty);
    let mut short_q = Vec::new();
    for topic in topics {
        if let Some(draft) = short_for_topic(topic, difficulty) {
            if validate_draft(&draft) {
                short_q.push(draft);
            }
        }
    }
    let long_q = long_for_topics(topics);
    let difficulty_note = if downgraded {
        "Where the notes did not support the requested difficulty, the question stays at standard difficulty instead of using invented wording.".into()
    } else {
        String::new()
    };
    Pool { fib, mcq, short_q, long_q, difficulty_note }
}

fn fib_for_topic(topic: &TopicMaterial, difficulty: &str, downgraded: &mut bool) -> Vec<Draft> {
    let mut drafts = Vec::new();
    let mut used_answers = Vec::new();
    let want_phrase = difficulty == "hard";
    for concept in &topic.concepts {
        let terms = fib_terms(concept);
        for term in terms {
            if want_phrase && !term.contains(' ') {
                continue;
            }
            if let Some(draft) = blank_from_topic(topic, &term, difficulty) {
                if !used_answers.iter().any(|a: &String| a.eq_ignore_ascii_case(&draft.correct_answer)) {
                    used_answers.push(draft.correct_answer.clone());
                    drafts.push(draft);
                }
            }
        }
    }
    if drafts.is_empty() {
        if want_phrase {
            *downgraded = true;
        }
        for concept in &topic.concepts {
            for term in fib_terms(concept) {
                if let Some(draft) = blank_from_topic(topic, &term, "standard") {
                    if !used_answers.iter().any(|a: &String| a.eq_ignore_ascii_case(&draft.correct_answer)) {
                        used_answers.push(draft.correct_answer.clone());
                        drafts.push(draft);
                    }
                }
            }
        }
    }
    if drafts.is_empty() {
        for sentence in sentences(&topic.reference_text) {
            if word_count(&sentence) < 6 {
                continue;
            }
            let tokens = content_words(&tokenize(&sentence));
            let Some(term) = tokens.into_iter().find(|t| t.chars().count() >= 5 && !is_stopword(t)) else {
                continue;
            };
            if let Some(draft) = blank_sentence(topic, &sentence, &term, "standard") {
                drafts.push(draft);
                break;
            }
        }
    }
    drafts
}

fn fib_terms(concept: &ConceptRef) -> Vec<String> {
    let mut terms = Vec::new();
    if concept.kind == "keyword" || concept.kind == "formula" {
        if !concept.content.trim().is_empty() {
            terms.push(concept.content.trim().to_string());
        }
    }
    if !concept.label.trim().is_empty() && concept.label.trim().chars().count() <= 40 {
        terms.push(concept.label.trim().to_string());
    }
    for alias in concept.aliases.split([',', ';', '|']) {
        let alias = alias.trim();
        if !alias.is_empty() {
            terms.push(alias.to_string());
        }
    }
    terms
}

fn blank_from_topic(topic: &TopicMaterial, term: &str, difficulty: &str) -> Option<Draft> {
    if term.chars().count() < 2 || is_stopword(&term.to_lowercase()) {
        return None;
    }
    for sentence in sentences(&topic.reference_text) {
        if word_count(&sentence) < 6 {
            continue;
        }
        if let Some(draft) = blank_sentence(topic, &sentence, term, difficulty) {
            return Some(draft);
        }
    }
    None
}

fn blank_sentence(topic: &TopicMaterial, sentence: &str, term: &str, difficulty: &str) -> Option<Draft> {
    let (start, end) = find_term(sentence, term)?;
    let answer = sentence[start..end].to_string();
    if !answer.chars().any(|c| c.is_alphabetic()) {
        return None;
    }
    let mut prompt = String::new();
    prompt.push_str(&sentence[..start]);
    prompt.push_str("______");
    prompt.push_str(&sentence[end..]);
    let mut alternatives = Vec::new();
    for concept in &topic.concepts {
        if concept.content.eq_ignore_ascii_case(&answer) || concept.label.eq_ignore_ascii_case(&answer) {
            for alias in concept.aliases.split([',', ';', '|']) {
                let alias = alias.trim();
                if !alias.is_empty() {
                    alternatives.push(alias.to_string());
                }
            }
        }
    }
    Some(Draft {
        question_type: "fib".into(),
        prompt,
        options: vec![],
        correct_answer: answer,
        alternatives,
        rubric_points: vec![],
        topic_ids: vec![topic.id.clone()],
        source_topic_id: topic.id.clone(),
        source_passage: sentence.to_string(),
        difficulty: difficulty.into(),
    })
}

struct Statement {
    topic_id: String,
    about: String,
    text: String,
    passage: String,
}

fn mcq_for_topics(topics: &[TopicMaterial], difficulty: &str) -> Vec<Draft> {
    let mut statements = Vec::new();
    for topic in topics {
        for concept in &topic.concepts {
            if concept.kind != "definition" && concept.kind != "fact" {
                continue;
            }
            let text = concept.content.trim();
            if text.chars().count() < 12 || text.chars().count() > 220 {
                continue;
            }
            let about = if concept.label.trim().is_empty() {
                topic.title.clone()
            } else {
                concept.label.trim().to_string()
            };
            let passage = if topic.reference_text.contains(text) {
                topic.reference_text.clone()
            } else {
                format!("{}\n{text}", topic.reference_text.trim())
            };
            statements.push(Statement {
                topic_id: topic.id.clone(),
                about,
                text: text.to_string(),
                passage,
            });
        }
    }
    let mut drafts = Vec::new();
    for statement in &statements {
        let mut distractors = Vec::new();
        let mut seen = std::collections::BTreeSet::new();
        seen.insert(norm_key(&statement.text));
        for other in &statements {
            if other.topic_id == statement.topic_id {
                continue;
            }
            let key = norm_key(&other.text);
            if !seen.insert(key) {
                continue;
            }
            distractors.push(other.text.clone());
            if distractors.len() == 3 {
                break;
            }
        }
        if distractors.len() < 3 {
            continue;
        }
        let mut options = vec![McqOption { id: "CORRECT".into(), text: statement.text.clone() }];
        for distractor in distractors {
            options.push(McqOption { id: "X".into(), text: distractor });
        }
        drafts.push(Draft {
            question_type: "mcq".into(),
            prompt: format!("Which of the following is stated about {}?", statement.about),
            options,
            correct_answer: "CORRECT".into(),
            alternatives: vec![],
            rubric_points: vec![statement.text.clone()],
            topic_ids: vec![statement.topic_id.clone()],
            source_topic_id: statement.topic_id.clone(),
            source_passage: statement.passage.clone(),
            difficulty: if difficulty.is_empty() { "standard".into() } else { difficulty.into() },
        });
        if drafts.len() == 40 {
            break;
        }
    }
    drafts
}

fn short_for_topic(topic: &TopicMaterial, difficulty: &str) -> Option<Draft> {
    let points = rubric_points(topic);
    if points.is_empty() || topic.reference_text.trim().is_empty() {
        return None;
    }
    let label = topic
        .concepts
        .iter()
        .find(|c| c.kind == "definition" && !c.label.trim().is_empty())
        .map(|c| c.label.trim().to_string());
    let (prompt, used_difficulty) = if difficulty == "easy" {
        if let Some(label) = label {
            (format!("Define {label}."), "easy")
        } else {
            (format!("Explain the topic: {}.", topic.title), "standard")
        }
    } else if difficulty == "hard" && points.len() >= 2 {
        (format!("Explain {} and how its main ideas relate. Use the facts from your notes.", topic.title), "hard")
    } else {
        (format!("Explain the topic: {}.", topic.title), "standard")
    };
    let passage = passage_with_points(topic, &points);
    Some(Draft {
        question_type: "short".into(),
        prompt,
        options: vec![],
        correct_answer: points.join(" "),
        alternatives: vec![],
        rubric_points: points,
        topic_ids: vec![topic.id.clone()],
        source_topic_id: topic.id.clone(),
        source_passage: passage,
        difficulty: used_difficulty.into(),
    })
}

fn long_for_topics(topics: &[TopicMaterial]) -> Vec<Draft> {
    let usable: Vec<&TopicMaterial> = topics
        .iter()
        .filter(|t| !t.reference_text.trim().is_empty() && !rubric_points(t).is_empty())
        .collect();
    if usable.len() < 2 {
        return Vec::new();
    }
    let mut drafts = Vec::new();
    let windows: Vec<&[&TopicMaterial]> = if usable.len() > 4 {
        vec![&usable[..4], &usable[usable.len() - 4..]]
    } else {
        vec![&usable[..]]
    };
    for window in windows {
        let mut points = Vec::new();
        let mut passage = String::new();
        let mut titles = Vec::new();
        let mut ids = Vec::new();
        for topic in window {
            titles.push(topic.title.clone());
            ids.push(topic.id.clone());
            passage.push_str(&format!("## {}\n{}\n", topic.title, topic.reference_text.trim()));
            for point in rubric_points(topic) {
                if points.len() < 8 {
                    points.push(point);
                }
            }
        }
        if points.is_empty() {
            continue;
        }
        let numbered = titles
            .iter()
            .enumerate()
            .map(|(i, title)| format!("{}. {title}", i + 1))
            .collect::<Vec<_>>()
            .join("\n");
        let prompt = format!(
            "Explain the following topics in detail and describe how they relate to each other:\n{numbered}\n\nBase your answer on the ideas in your notes. Include the important definitions, facts, and terms."
        );
        for point in &points {
            if !passage.contains(point) {
                passage.push_str(point);
                passage.push('\n');
            }
        }
        drafts.push(Draft {
            question_type: "long".into(),
            prompt,
            options: vec![],
            correct_answer: points.join(" "),
            alternatives: vec![],
            rubric_points: points,
            topic_ids: ids.clone(),
            source_topic_id: ids[0].clone(),
            source_passage: passage,
            difficulty: "standard".into(),
        });
    }
    drafts
}

fn rubric_points(topic: &TopicMaterial) -> Vec<String> {
    let mut points = Vec::new();
    for concept in &topic.concepts {
        if matches!(concept.kind.as_str(), "definition" | "fact" | "expected_point" | "formula")
            && !concept.content.trim().is_empty()
        {
            let text = if !concept.label.trim().is_empty() && concept.kind == "definition" {
                format!("{}: {}", concept.label.trim(), concept.content.trim())
            } else {
                concept.content.trim().to_string()
            };
            if !points.iter().any(|p: &String| p == &text) {
                points.push(text);
            }
        }
    }
    points
}

fn passage_with_points(topic: &TopicMaterial, points: &[String]) -> String {
    let mut passage = topic.reference_text.trim().to_string();
    for point in points {
        if !passage.contains(point) {
            passage.push('\n');
            passage.push_str(point);
        }
    }
    passage
}

fn validate_draft(draft: &Draft) -> bool {
    if draft.prompt.trim().is_empty()
        || draft.correct_answer.trim().is_empty()
        || draft.source_topic_id.is_empty()
        || draft.source_passage.trim().is_empty()
    {
        return false;
    }
    match draft.question_type.as_str() {
        "fib" => {
            draft.prompt.contains("______")
                && find_term(&draft.source_passage, &draft.correct_answer).is_some()
        }
        "mcq" => {
            draft.options.len() == 4
                && draft.options.iter().filter(|o| o.id == "CORRECT").count() == 1
                && draft.source_passage.contains(draft.options.iter().find(|o| o.id == "CORRECT").map(|o| o.text.as_str()).unwrap_or(""))
        }
        "short" | "long" => draft.rubric_points.iter().all(|p| draft.source_passage.contains(p)),
        _ => false,
    }
}

fn validate_question(question: &ExamQuestion) -> AppResult<()> {
    if question.prompt.trim().is_empty()
        || question.correct_answer.trim().is_empty()
        || question.source_topic_id.is_empty()
        || question.source_passage.trim().is_empty()
        || question.max_marks <= 0
    {
        return Err(AppError::Invalid(
            "A question was rejected because it was not supported by the saved notes.".into(),
        ));
    }
    if question.question_type == "mcq" {
        if question.options.len() != 4 {
            return Err(AppError::Invalid("An MCQ did not have four options.".into()));
        }
        let matches = question
            .options
            .iter()
            .filter(|o| o.id.eq_ignore_ascii_case(&question.correct_answer))
            .count();
        if matches != 1 {
            return Err(AppError::Invalid(
                "An MCQ did not have exactly one correct option.".into(),
            ));
        }
    }
    if question.question_type == "fib" && !question.prompt.contains("______") {
        return Err(AppError::Invalid("A fill-in-the-blank question had no blank.".into()));
    }
    Ok(())
}

fn norm_key(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

pub fn shuffle<T>(items: &mut [T], rng: &mut impl Rng) {
    if items.len() < 2 {
        return;
    }
    for i in (1..items.len()).rev() {
        let j = rng.gen_range(0..=i);
        items.swap(i, j);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn concept(kind: &str, label: &str, content: &str) -> ConceptRef {
        ConceptRef {
            kind: kind.into(),
            label: label.into(),
            content: content.into(),
            aliases: String::new(),
        }
    }

    fn rich(i: usize) -> TopicMaterial {
        let title = format!("Topic {i}");
        let term = format!("Concept{i}");
        let fact = format!("The value of {term} is exactly {i} units in this note.");
        TopicMaterial {
            id: format!("t{i}"),
            title: title.clone(),
            reference_text: format!(
                "{title} covers {term} in a complete sentence for study. {fact} A student should remember {term} when explaining {title} today."
            ),
            language: "en".into(),
            concepts: vec![
                concept("definition", &term, &format!("{term} is the central idea of {title}.")),
                concept("fact", "", &fact),
                concept("keyword", "", &term),
                concept("expected_point", "", &format!("Remember {term} for {title}.")),
            ],
        }
    }

    #[test]
    fn full_paper_keeps_exact_weighting() {
        let topics: Vec<_> = (0..12).map(rich).collect();
        let proposal = propose(&topics, "standard");
        let full = proposal.offers.iter().find(|o| o.size_id == "full").unwrap();
        assert!(full.feasible, "{:?}", proposal.material_note);
        assert_eq!(full.total_marks, 100);
        assert_eq!(full.section_a_marks, 30);
        assert_eq!(full.section_b_marks, 40);
        assert_eq!(full.section_c_marks, 30);
        assert_eq!(full.percent_a, 30.0);
        assert_eq!(full.percent_b, 40.0);
        assert_eq!(full.percent_c, 30.0);
        let (offer, questions) = build_paper(&topics, "standard", "full", 42).unwrap();
        assert_eq!(questions.len(), 34);
        assert_eq!(questions.iter().map(|q| q.max_marks).sum::<i64>(), 100);
        assert_eq!(offer.rounding_note.contains("30%"), true);
        let fib: i64 = questions.iter().filter(|q| q.question_type == "fib").map(|q| q.max_marks).sum();
        let mcq: i64 = questions.iter().filter(|q| q.question_type == "mcq").map(|q| q.max_marks).sum();
        let rest: i64 = questions.iter().filter(|q| q.question_type == "short" || q.question_type == "long").map(|q| q.max_marks).sum();
        assert_eq!((fib, mcq, rest), (30, 40, 30));
        for question in &questions {
            assert!(!question.source_topic_id.is_empty());
            assert!(!question.source_passage.trim().is_empty());
            assert!(!question.correct_answer.trim().is_empty());
            if question.question_type == "mcq" {
                assert_eq!(question.options.len(), 4);
                assert_eq!(
                    question.options.iter().filter(|o| o.id == question.correct_answer).count(),
                    1
                );
            }
        }
    }

    #[test]
    fn neuron_blank_uses_the_source_sentence() {
        let topic = TopicMaterial {
            id: "n".into(),
            title: "Neuron".into(),
            reference_text: "A neuron consists of a cell body, dendrites, and an axon.".into(),
            language: "en".into(),
            concepts: vec![concept("keyword", "", "axon")],
        };
        let (_offer, questions) = build_paper(&[topic], "standard", "custom", 7).unwrap();
        let fib = questions.iter().find(|q| q.question_type == "fib").unwrap();
        assert!(fib.prompt.contains("______"));
        assert_eq!(fib.correct_answer.to_ascii_lowercase(), "axon");
        assert!(fib.source_passage.to_ascii_lowercase().contains("axon"));
        assert!(!fib.prompt.to_ascii_lowercase().contains("axon"));
    }

    #[test]
    fn insufficient_notes_do_not_invent_a_full_paper() {
        let topic = rich(1);
        let proposal = propose(&[topic], "standard");
        let full = proposal.offers.iter().find(|o| o.size_id == "full").unwrap();
        assert!(!full.feasible);
        assert!(full.reason.contains("can support"));
    }

    #[test]
    fn same_seed_builds_the_same_paper() {
        let topics: Vec<_> = (0..12).map(rich).collect();
        let a = build_paper(&topics, "standard", "full", 99).unwrap();
        let b = build_paper(&topics, "standard", "full", 99).unwrap();
        let prompts = |qs: &[ExamQuestion]| qs.iter().map(|q| q.prompt.clone()).collect::<Vec<_>>();
        assert_eq!(prompts(&a.1), prompts(&b.1));
    }

    #[test]
    fn section_mark_rounding_is_disclosed_by_the_allocator() {
        assert_eq!(section_marks(100, [30, 40, 30]), [30, 40, 30]);
        assert_eq!(section_marks(50, [30, 40, 30]), [15, 20, 15]);
        assert_eq!(section_marks(10, [30, 40, 30]), [3, 4, 3]);
        assert_eq!(section_marks(1, [30, 40, 30]).iter().sum::<i64>(), 1);
        assert_eq!(split_marks(10, 3).iter().sum::<i64>(), 10);
    }

    #[test]
    fn shuffle_keeps_every_topic_once() {
        let mut rng = StdRng::seed_from_u64(3);
        let mut ids: Vec<_> = (0..8).map(|n| format!("t{n}")).collect();
        let original = ids.clone();
        shuffle(&mut ids, &mut rng);
        assert_eq!(ids.len(), original.len());
        for id in &original {
            assert_eq!(ids.iter().filter(|x| *x == id).count(), 1);
        }
    }
}
