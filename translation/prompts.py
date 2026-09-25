"""Prompt templates and JSON schemas for every agent.

Prompt layout (prompt caching is a prefix match, so stable content comes first):

  system[0]  PROJECT_BRIEF + the whole Portuguese book       cache breakpoint (1h)
  system[1]  glossary + style guide + character profiles     cache breakpoint (1h)
  user       the agent's role and the task for this call     (not cached)

Every agent shares system[0] and system[1], so after the first call of a run the
book is read from cache.
"""

import json

from docx_io import SourceParagraph
from glossary import Glossary

SPEAKER_LABELS = {
    "ilana": "Ilana (the author, a human medium, narrating her own experience)",
    "baruck": "Master Baruck (a spiritual mentor, discarnate)",
    "et": "the ETs (extraterrestrial brothers and sisters communicating through the medium)",
    "unmarked": "unmarked (no speaker highlight)",
}

PROJECT_BRIEF = """\
You are part of a small team producing the English edition of a Brazilian Spiritist \
(Kardecist) book written by the medium Ilana Skitnevsky. The book records messages \
received from Master Baruck, a spiritual mentor, and from extraterrestrial Spirits \
("the ETs"), together with Ilana's own narration.

The English edition will be read by English-speaking Spiritists and will also be \
recorded as a podcast in which each speaker has a different voice. Every paragraph is \
labelled with its speaker: ilana, baruck or et. The label never changes in translation.

Doctrinal frame: Allan Kardec's Codification (The Spirits' Book, The Mediums' Book, The \
Gospel According to Spiritism, Heaven and Hell, Genesis) and the established English \
Spiritist vocabulary (Anna Blackwell's translations, International Spiritist Council \
usage). Spiritist terms are technical terms of a scientific-philosophical-moral \
doctrine: they must never be secularized ("discarnation" is not "death"), \
occultized ("mediumship" is not "witchcraft" or "channeling"), or confused with \
Anglo-American Spiritualism.

The complete Portuguese book follows. Each line is `[paragraph id | speaker] text`. \
Text between ** markers is bold in the original.
"""


def render_book(paragraphs: list[SourceParagraph], texts: dict[str, str] | None = None) -> str:
    """Render the book as `[P0012 | et] text` lines (source text, or `texts` by id)."""
    lines = []
    for p in paragraphs:
        if not p.translatable:
            continue
        text = p.text if texts is None else texts.get(p.id)
        if text is None:
            continue
        lines.append(f"[{p.id} | {p.speaker}] {text}")
    return "\n".join(lines)


def render_guidance(glossary: Glossary, bible: dict | None) -> str:
    parts = ["# Mandatory glossary", "", glossary.render(), ""]
    if bible:
        parts += ["# Style guide", "", bible["style_guide"], "", "# Speakers and their voices", ""]
        for character in bible["characters"]:
            parts.append(f"- **{character['speaker']}** — {character['description']} Voice: {character['voice']}")
    else:
        parts += ["# Style guide", "",
                  "Serene, philosophical, dignified; the register of classical Kardecist literature."]
    parts += ["", "# Speaker labels", ""] + [f"- {k}: {v}" for k, v in SPEAKER_LABELS.items()]
    return "\n".join(parts)


def system_blocks(source_book: str, guidance: str) -> list[dict]:
    cache = {"type": "ephemeral", "ttl": "1h"}
    return [
        {"type": "text", "text": f"{PROJECT_BRIEF}\n<source_book>\n{source_book}\n</source_book>",
         "cache_control": cache},
        {"type": "text", "text": guidance, "cache_control": cache},
    ]


def chunk_payload(paragraphs: list[SourceParagraph]) -> str:
    return json.dumps([{"id": p.id, "speaker": p.speaker, "text": p.text} for p in paragraphs],
                      ensure_ascii=False, indent=1)


def translations_payload(translations: dict[str, str], ids: list[str]) -> str:
    return json.dumps([{"id": i, "text": translations[i]} for i in ids if i in translations],
                      ensure_ascii=False, indent=1)


# --------------------------------------------------------------------------------------
# JSON schemas (structured outputs)
# --------------------------------------------------------------------------------------

def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


_STR = {"type": "string"}
_SEVERITY = {"type": "string", "enum": ["critical", "major", "minor"]}

FLAG = _obj({
    "paragraph_id": _STR,
    "original_term": _STR,
    "assigned_translation": _STR,
    "context_snippet": _STR,
    "ai_reasoning": _STR,
})

BIBLE_SCHEMA = _obj({
    "style_guide": _STR,
    "characters": {"type": "array", "items": _obj({"speaker": _STR, "description": _STR, "voice": _STR})},
    "terms": {"type": "array", "items": _obj({"source": _STR, "target": _STR, "rationale": _STR})},
})

TRANSLATION_SCHEMA = _obj({
    "translations": {"type": "array", "items": _obj({"id": _STR, "text": _STR})},
    "flags": {"type": "array", "items": FLAG},
})

CRITIQUE_SCHEMA = _obj({
    "issues": {"type": "array", "items": _obj({
        "paragraph_id": _STR,
        "severity": _SEVERITY,
        "category": {"type": "string", "enum": [
            "secularized_concept", "glossary_violation", "doctrinal_error", "tone",
            "speaker_voice", "omission", "addition", "mistranslation", "english_quality", "formatting"]},
        "problem": _STR,
        "suggested_fix": _STR,
    })},
    "flags": {"type": "array", "items": FLAG},
})

BOOK_REVIEW_SCHEMA = _obj({
    "overall_verdict": {"type": "string", "enum": ["fit_for_publication", "fit_after_revisions", "not_fit"]},
    "report": _STR,
    "scores": {"type": "array", "items": _obj({
        "dimension": {"type": "string", "enum": [
            "doctrinal_fidelity", "terminology_consistency", "voice_ilana", "voice_baruck", "voice_et",
            "narrative_coherence", "english_literary_quality", "read_aloud_suitability"]},
        "score": {"type": "integer"},
        "commentary": _STR,
    })},
    "chapters": {"type": "array", "items": _obj({
        "chunk_id": _STR,
        "verdict": {"type": "string", "enum": ["fit", "needs_revision", "not_fit"]},
        "notes": _STR,
    })},
    "decision_verdicts": {"type": "array", "items": _obj({
        "decision_id": _STR,
        "verdict": {"type": "string", "enum": ["agree", "disagree", "uncertain"]},
        "preferred_translation": _STR,
        "rationale": _STR,
    })},
    "findings": {"type": "array", "items": _obj({
        "paragraph_ids": {"type": "array", "items": _STR},
        "category": _STR,
        "severity": _SEVERITY,
        "problem": _STR,
        "suggested_revision": _STR,
    })},
})


# --------------------------------------------------------------------------------------
# Agent task prompts (user messages)
# --------------------------------------------------------------------------------------

FLAG_INSTRUCTIONS = """\
Flag decisions a human reviewer should check: terms with more than one theological \
reading, doctrinal terms not in the glossary, and judgment calls. Typical examples: \
"fluido", "sintonia", "vibração", "espírito errante", "energia", "egrégora", "plano", \
"irmãos estelares", forms of address such as "Irmã", invented or ET-specific words, \
and idioms with religious weight. For each flag give the paragraph id, the Portuguese \
term, the English you used, a short context snippet (one sentence, in Portuguese) and \
one or two sentences of reasoning. Do not flag routine vocabulary, and flag each \
term once per chunk."""

BIBLE_TASK = """\
ROLE: Senior editor preparing the English edition.

Read the whole book above before the translation starts, and produce the reference \
material every translator will use:

1. style_guide — how the English should read: register, sentence rhythm, how to \
render dialogue introduced by dashes, forms of address, capitalization conventions \
(e.g. Spirit, Master), how to handle Portuguese honorifics and religious idiom. \
Classical Kardecist register: serene, philosophical, dignified; clear enough to be \
read aloud.
2. characters — one entry per speaker label (ilana, baruck, et): who they are and \
how their voice sounds (vocabulary, formality, emotional tone, recurring \
expressions), so each keeps a consistent voice across the whole book.
3. terms — recurring doctrinal terms, invented or ET-specific terms, proper names \
and recurring expressions that need one consistent English rendering. Do not \
repeat terms already in the mandatory glossary unless you believe the glossary is \
wrong for this book — in that case include the term and explain why in the \
rationale (the glossary still applies until a human decides).
"""

TRANSLATOR_TASK = """\
ROLE: Literary translator (Brazilian Portuguese → English), specialist in Spiritist \
literature.

Translate every paragraph in <source_chunk> below. You have the whole Portuguese book \
above for context: use it to understand references, foreshadowing and how each \
speaker talks, but translate only this chunk.

Rules:
1. Return exactly one translation per paragraph id in the chunk, and no other ids.
2. The mandatory glossary is binding. Human reviewer decisions override everything.
3. Keep each speaker's voice as described in the guidance. Pay attention to the \
emotional state of characters linked to specific dialog markers (dashes, quotation \
marks, exclamations, forms of address).
4. Be faithful: no omissions, additions, summaries or explanations, and no \
translator's notes (except the first-use glosses the glossary requires).
5. Bold markup: if a source paragraph contains **...**, wrap the corresponding \
English words in ** as well. Never add ** where the source has none.
6. Headings: "Capítulo N: Título" → "Chapter N: Title"; "Prefácio" → "Preface"; \
"Posfácio" → "Afterword".
7. Keep proper names (Ilana Skitnevsky, Baruck, Gandhi, ...) unchanged.
8. The English must continue naturally from <preceding_english>.

{flag_instructions}
{reviewer_notes}
<preceding_english>
{preceding_english}
</preceding_english>

<source_chunk>
{chunk}
</source_chunk>
"""

REVIEWER_NOTES_BLOCK = """
Notes from the human review of an earlier version of this chunk — apply them:
{notes}
"""

CRITIC_TASK = """\
ROLE: Doctrinal proofreader for Spiritist (Kardecist) literature — rigid, precise, \
bilingual.

Compare the draft English translation with the Portuguese source chunk and list real \
problems only:
- Spiritist concepts secularized or genericized ("desencarnou" → "died"; \
"mediunidade" → "psychic ability"; "Espírito" → "ghost"; "Espiritismo" → \
"spiritualism"), or rendered with occult/New Age connotations.
- Glossary violations (the mandatory glossary is binding).
- Doctrinal errors: meaning that contradicts or distorts the source's doctrine.
- Tone drift away from the dignified register of classical Kardecist literature.
- Speaker voice that does not match the speaker label and profile.
- Omissions, additions, mistranslations, poor or unnatural English.
- Bold markup (**) missing or misplaced relative to the source.

For each issue give the paragraph id, severity, category, the problem and the exact \
fix. Return an empty issues list if the draft is correct — do not invent issues.

Also flag judgment calls the translator should have flagged but did not.
{flag_instructions}

<source_chunk>
{chunk}
</source_chunk>

<draft_translation>
{draft}
</draft_translation>

<translator_flags>
{flags}
</translator_flags>
"""

REFINER_TASK = """\
ROLE: Literary translator (Brazilian Portuguese → English), revising a chunk.

Revise the translation below so that every listed issue is fixed. Change only what \
the issues require; keep everything else exactly as it is. The mandatory glossary \
and the rules for speaker voice and ** bold markup still apply.

Return the complete chunk: exactly one translation per paragraph id in \
<source_chunk>, including paragraphs you did not change. Flag any new judgment call \
you make while fixing the issues.
{flag_instructions}

<source_chunk>
{chunk}
</source_chunk>

<current_translation>
{draft}
</current_translation>

<issues_to_fix>
{issues}
</issues_to_fix>
"""

VALIDATION_RETRY = """

Your previous answer could not be used: {error}
Answer again, following the rules exactly."""

BOOK_REVIEWER_TASK = """\
ROLE: Senior doctrinal and literary reviewer of Spiritist books.

You are an experienced reviewer of Spiritist literature, fluent in Brazilian \
Portuguese and English. You have reviewed Kardecist works for publication for many \
years, you know Allan Kardec's Codification closely, the English translations of the \
Codification, and how Spiritist concepts are established in English. A publisher \
has asked you whether this English translation is fit to be published and recorded \
as a podcast.

You did not take part in the translation. Read the entire Portuguese book (above) \
and the entire English translation (<english_book>) side by side, as a reviewer \
reads a manuscript, and judge the translation as a whole:

- Doctrinal fidelity: every Spiritist concept keeps its Kardecist meaning; nothing \
secularized, occultized or confused with Anglo-American Spiritualism; nothing added \
that the source does not teach.
- Terminology consistency across the whole book (the same concept rendered the same \
way from the first chapter to the last), and agreement with the mandatory glossary.
- The voice of each speaker across the whole book — Ilana, Master Baruck, the ETs — \
consistent and faithful to the Portuguese.
- Narrative coherence: references, recurring images and ideas connect as they do in \
the source.
- English literary quality and dignity of register.
- Suitability for being read aloud.

Then:
1. overall_verdict and report — your reviewer's report to the publisher (a few \
paragraphs: strengths, main problems, what must change before publication).
2. scores — every dimension, 1 (unacceptable) to 5 (excellent), with commentary.
3. chapters — one entry per chunk listed in <chunks>{focus_note}.
4. decision_verdicts — one entry for every item in <decisions>: agree, disagree or \
uncertain; preferred_translation (empty string if you agree); rationale. Judge each \
decision on the evidence of the whole book.
5. findings — concrete problems, each with the paragraph ids, category, severity, \
the problem and the revised English you recommend. Include systematic problems once, \
listing the affected paragraph ids. Do not invent problems; an empty list is a valid \
answer.

Do not rewrite the book; your findings go to a human reviewer who decides.

<chunks>
{chunks}
</chunks>

<decisions>
{decisions}
</decisions>

<english_book>
{english_book}
</english_book>
"""
