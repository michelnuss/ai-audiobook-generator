# Book Translation Pipeline (PT → EN) — Design

Date: 2026-09-25
Status: Draft for review

## 1. Purpose

Translate the Spiritist book `Ilana-Livro-LIMPO colorido (1).docx` from Brazilian
Portuguese into English, producing a **new English `.docx`** in which every
paragraph keeps the highlight color that identifies its speaker. The English
document feeds the existing podcast/audiobook app (`app/`), which assigns a
different voice per speaker based on those highlight colors.

Quality is the top priority: doctrinal precision (Kardecist terminology), a
consistent voice per character across the whole book, and a human-reviewable
record of every non-obvious terminology decision.

### Success criteria

1. `translation/output/Ilana-Book-EN.docx` exists; every source paragraph has
   exactly one English counterpart carrying the **same highlight color**
   (YELLOW = Ilana, TURQUOISE = Baruck, BRIGHT_GREEN = ET) and the same run
   formatting (bold, font, size).
2. Every seed-glossary term is translated per the glossary everywhere it occurs.
3. Interrupting the run at any point and re-running resumes at the first
   unfinished chunk without repeating paid work.
4. `translation_review.md` lets a reviewer inspect every flagged decision —
   with the whole-book Spiritist reviewer's verdict — without reading the whole book.
5. A reviewer's term correction is applied by one command that re-translates
   only the affected chunks and rebuilds the document.

## 2. Facts about the source document (measured)

| Property | Value |
|---|---|
| Paragraphs | 951 (947 `Normal`, 4 `Normal (Web)`) |
| Words | ~29,800 (~50k tokens) |
| Non-empty runs | 935 — almost always one run per paragraph |
| Speaker marking | **Highlight color** (`run.font.highlight_color`), **not** RGB font color. No run has an RGB color set. |
| Highlight distribution (chars) | BRIGHT_GREEN 161k (ET), YELLOW 20k (Ilana), TURQUOISE 1k (Baruck) |
| Paragraphs mixing highlights | 0 |
| Chapter markers | Text lines `Capítulo N: <title>` (no Heading styles) |
| Bold runs | 429 |
| Tables / extra sections | 0 / 1 |

Consequences:
- Speaker identity is a **paragraph-level** property. The model translates a
  paragraph as a unit; no intra-paragraph run alignment is needed.
- The spec request to read/write RGB colors is replaced by highlight colors —
  RGB would find nothing and silently drop all speaker identity.

## 3. Model & platform (verified against current API docs)

- Model: **Claude Opus 5.5** on **Microsoft Foundry (Azure)** via the official
  Python `anthropic` SDK, client class `AnthropicFoundry`. Deployment/model name
  is configurable (default `claude-opus-5-5`).
- **`temperature` is not supported on Opus 5.5** (returns HTTP 400). Precision
  is controlled with `output_config.effort` (default `high`, configurable) plus
  strict prompts and structured outputs. Adaptive thinking is always on.
- Supported on Foundry and used here: 1M context, prompt caching (1h TTL),
  structured outputs (`output_config.format` JSON schema), streaming.
- Not available on Foundry: Batches API, server-side refusal fallbacks. Not needed.
- No assistant prefill (400 on this model); JSON is obtained via structured outputs.
- All API keys/endpoints are read from `.env`; `.env.example` ships with blank values.

## 4. Architecture

### 4.1 Core idea: whole book as cached context, chunked output

The full Portuguese book (~50k tokens) fits easily in the context window. Every
agent call starts with the **same cached prefix**:

1. System prompt (role, rules, glossary, style guide, character profiles)
2. The **entire source book**, rendered as `[P0001][ET] text…` lines

Only the per-chunk instruction varies after the cache breakpoint. The
translator therefore sees foreshadowing, later reveals and each character's
full voice, instead of a lossy rolling summary. With prompt caching, re-reading
the book per call costs cache-read rates. The rolling `narrative_summary` from
the original brief is dropped as redundant (YAGNI).

Continuity of the **English** prose is provided by including the last ~40
already-translated English paragraphs preceding the chunk.

### 4.2 Pipeline per run

```
bible (once) ──► for each chunk in order:
                   translate ──► critique ──(issues?)──► refine
                        │                                  │
                        └──────────────► validate ◄────────┘
                                            │
                                   save state + review log
                 ──► Spiritist Book Reviewer (whole book, once)
                 ──► build docx
```

### 4.3 Components (all in `translation/`)

| File | Responsibility |
|---|---|
| `config.py` | Load `.env`; paths, model name, effort, chunk size |
| `docx_io.py` | Read source into `Paragraph(id, text, speaker, highlight)`; write English docx |
| `chunker.py` | Keep chapters (`Capítulo N:`, Prefácio, Posfácio) whole and pack consecutive chapters into chunks of up to 2,500 words (15 chunks for this book); split a larger chapter at paragraph boundaries |
| `glossary.py` | Seed Spiritist glossary + merge bible terms + reviewer corrections; render for prompts |
| `state.py` | `global_state.json` load/atomic save; chunk status; translations by paragraph id |
| `prompts.py` | All prompt templates and JSON schemas |
| `llm.py` | `AnthropicFoundry` client, streaming call, structured output parsing, `tenacity` retry |
| `agents.py` | `BookBibleAgent`, `TranslatorAgent`, `CriticAgent`, `RefinerAgent`, `BookReviewerAgent` |
| `review.py` | Review log (JSON + Markdown render), corrections workflow |
| `translate.py` | CLI: `bible`, `run`, `review`, `status`, `apply-corrections`, `build` |
| `tests/` | pytest suite with a fake LLM |
| `.env.example`, `requirements.txt`, `README.md` | Setup |

## 5. Agents

All agents share the cached prefix (§4.1) and return JSON via structured outputs.

### 5.1 Book Bible (once, before translation)
Reads the whole book and returns:
- `style_guide`: register and tone of the narration (seeded with "serene,
  philosophical, dignified; classical Kardecist register").
- `characters`: per speaker (`ilana`, `baruck`, `et`) — who they are, voice,
  vocabulary, how they address others.
- `terms`: recurring doctrinal terms, invented terms, proper names, with
  proposed English rendering and a one-line rationale.

Stored in `state/book_bible.json`. Terms are merged into the working glossary
**below** seed terms (seed and reviewer corrections always win). Each bible
term is also added to the review log so a human can approve it.

### 5.2 Translator
Input (after cache): chunk paragraphs `[{id, speaker, text}]`, preceding English
context, a note to attend to each speaker's emotional state and dialog markers.
Output: `{translations: [{id, text}], flags: [{original_term,
assigned_translation, context_snippet, ai_reasoning}]}`.
Flags are required for terms with multiple theological readings or judgment
calls (e.g. *fluido, sintonia, vibração, espírito errante*).

### 5.3 Critic (doctrinal QA)
Input: source chunk, draft, glossary. Checks: secularized/genericized Spiritist
concepts, glossary violations, tone drift from classical Kardecist literature,
speaker voice mismatch, omissions/additions, mistranslation.
Output: `{issues: [{id, severity, problem, suggested_fix}], flags: [...]}`.

### 5.4 Refiner (single turn, only if critic found issues)
Input: source chunk, draft, issues. Output: same schema as translator (full
chunk). Exactly one refinement pass per chunk.

### 5.5 Spiritist Book Reviewer (whole book, independent)
Acts as a senior reviewer/editor of Spiritist literature — fluent in Brazilian
Portuguese and English, steeped in Allan Kardec's Codification (*The Spirits'
Book*, *The Mediums' Book*, *The Gospel According to Spiritism*, *Heaven and
Hell*, *Genesis*) and the established English Spiritist vocabulary (Anna
Blackwell's translations, the International Spiritist Council's conventions).
It reviews the translation the way a publisher's doctrinal reviewer reviews a
manuscript: **reading the entire Portuguese book and the entire English
translation side by side**, and deciding whether the English book is fit.

- **Runs once, after every chunk is final** (`translate.py review`, invoked
  automatically at the end of `run`). Input: the whole source book and the
  whole English book, both labelled by paragraph id and speaker (~100k tokens,
  well within the context window), plus the list of flagged decisions
  (`original_term` → `assigned_translation` + context).
- **Independence:** it never sees the translator's or critic's reasoning or the
  critic's issues, so it cannot anchor on their justifications.
- **Output (`review/book_review.json` + `review/book_review.md`):**
  - `overall_verdict ∈ {fit_for_publication, fit_after_revisions, not_fit}` and
    a reviewer's report (a few paragraphs, like a publisher's reader report).
  - Scores 1–5 with commentary on: doctrinal fidelity to the Codification,
    terminology consistency across the book, each character's voice across the
    book (Ilana, Baruck, ET), narrative coherence, English literary quality,
    suitability for being read aloud (podcast).
  - Per-chapter assessment: verdict + short notes.
  - A verdict on **every flagged decision**: `agree | disagree | uncertain`,
    `preferred_translation`, `rationale` — now judged with whole-book context.
  - **Findings**: concrete problems with `paragraph_ids`, `category`,
    `severity (critical|major|minor)`, `problem`, `suggested_revision`.
- It does **not** edit text. Findings and verdicts are added to the review log
  for the human reviewer to accept or reject.
- `--chapters` option re-reviews only chunks changed since the last review
  (still with the whole book in context), used after corrections.

## 6. Validation

After translator and refiner, code verifies: every chunk paragraph id appears
exactly once, no unknown ids, no empty text. On failure the call is retried
(up to 2 more times) with the validation error appended; after that the run
stops with a clear error and the state untouched for that chunk.

## 7. State & resume

`translation/state/global_state.json` (written atomically: temp file + rename
after every stage of every chunk):

```json
{
  "source_file": "...", "source_sha256": "...",
  "bible_done": true,
  "chunks": {
    "c03": {"paragraph_ids": ["P0102", "..."], "status": "final",
            "translations": {"P0102": "..."}}}
  }
}
```

Chunk status progression: `pending → translated → critiqued → final`.
The book review is tracked separately (`book_review_done`, `reviewed_chunks`).
`run` resumes each chunk from its last completed stage. If the source file hash
changes, the run refuses to continue and asks for `--reset`.

## 8. Glossary

Seed (locked; enforced in every prompt and checked by the critic):

| Portuguese | English |
|---|---|
| Desencarne / Desencarnação | Discarnation (never "death") |
| Desencarnar / desencarnado | to discarnate / discarnate |
| Encarnado | incarnate |
| Reencarnação | Reincarnation |
| Perispírito | Perispirit |
| Obsessão / Subjugação / Fascinação | Obsession / Subjugation / Fascination |
| Fluido Cósmico Universal | Universal Cosmic Fluid |
| Erraticidade | Erraticity |
| Espírito errante | errant Spirit |
| Passe | passe (spiritual healing) — "passe" in text; gloss on first use |
| Plano Espiritual | Spiritual Realm |
| Umbral | Umbral (the Threshold) — gloss on first use |
| Mediunidade / Médium | Mediumship / Medium |
| Espiritismo / Espírita | Spiritism / Spiritist |
| Plano material | material plane |

Precedence: reviewer correction > seed > bible term.

## 9. Review log & corrections

`translation/review/translation_review.json` is the source of truth;
`translation_review.md` is regenerated from it after every chunk, sorted with
reviewer disagreements and critical/major findings first.

Entry:
```json
{"id": "R0042", "chunk": "c03", "paragraph_id": "P0110", "source": "translator|critic|bible|book_reviewer",
 "original_term": "sintonia", "assigned_translation": "attunement",
 "context_snippet": "...", "ai_reasoning": "...",
 "reviewer": {"verdict": "agree", "preferred_translation": null, "rationale": "..."},
 "review_status": "pending", "correction": null}
```

Reviewer workflow:
- Term is correct → nothing to do (optionally set `review_status: "approved"`).
- Term must change → set `"correction": "<new English>"`, then run
  `python translate.py apply-corrections`. This:
  1. adds the correction to the glossary as a locked term;
  2. finds every chunk whose source contains `original_term` (case- and
     accent-insensitive);
  3. re-runs translate → critique → refine for those chunks only;
  4. marks the entry `review_status: "applied"`, rebuilds the docx.
- Book-reviewer finding to act on → set `"review_status": "accept"` (optionally
  edit `correction` with the wording you want). `apply-corrections` sends
  accepted findings to the Refiner as issues for the affected chunks.
- After corrections, `translate.py review --changed` re-reviews the changed
  chapters with the whole book in context.

## 10. Output document

`translation/output/Ilana-Book-EN.docx` is a new file; the source is never
modified. To reproduce page setup, fonts and paragraph styles exactly, it is
built from a copy of the source document: for each paragraph, the English text
replaces the text of the first run, remaining runs are removed, and the first
run's formatting — including `highlight_color` — is kept. Paragraphs with more
than one formatted run (rare) get the first run's formatting and are listed in
the build log. Empty paragraphs (spacing) are preserved as-is. Chapter lines
become `Chapter N: <English title>`.

A post-build check re-reads the output and asserts paragraph count and the
per-paragraph highlight sequence equal the source.

## 11. Error handling

- `tenacity` exponential backoff (with jitter) on `RateLimitError`,
  `APIConnectionError`, `APITimeoutError`, `InternalServerError` (5xx, 529);
  no retry on 400/401/403/404. SDK built-in retries disabled to avoid double retry.
- `stop_reason == "refusal"`: logged, chunk marked `failed`, run continues to
  the next chunk; `status` lists failed chunks. (No server-side fallbacks on
  Foundry.)
- `stop_reason == "max_tokens"`: the chunk is split in half and retried.
- Missing `.env` values: fail fast before any API call.
- Cache usage (`cache_read_input_tokens`) and token totals are logged per call
  and summarized by `status`.

## 12. Testing

pytest with a `FakeLLM` returning canned JSON:
- docx round-trip: highlights, bold and paragraph count preserved (tiny fixture
  docx generated in the test).
- chunker: chapter boundaries, oversized-chapter splitting.
- validation: missing / extra / empty ids rejected.
- state: atomic save, resume from each stage, source-hash guard.
- review: flags appended, markdown rendered, `apply-corrections` selects the
  right chunks and locks the term.
- book reviewer: prompt contains the whole source and translation and never
  the translator/critic reasoning; findings land in the review log.

A `--limit-chunks N` option allows a cheap real smoke test on the first chunk.

## 13. Out of scope

- Changing `app/parse_colors.py` to detect English `Chapter N:` headings
  (one-line follow-up in `app/`).
- Translating to languages other than English.
- A UI for reviewing terms (the Markdown/JSON files are the interface).

## 14. Cost estimate

~12–15 chunks × ~3 calls each plus one ~100k-token whole-book review with a ~55k-token cached prefix. Cache reads at
$0.20/MTok make the prefix cheap; output (+thinking) dominates. Expected total
for a full run: roughly $15–40 at effort `high`. `status` prints actual spend.
