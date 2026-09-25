# Book translator — PT-BR → English, with a Spiritist reviewer agent

Translates *Ilana-Livro-LIMPO colorido (1).docx* into English with Claude Opus 5.5
on Microsoft Foundry (Azure). It produces a new `.docx` in which every paragraph keeps
its speaker highlight (yellow = Ilana, turquoise = Baruck, bright green = ET), ready
for the multi-voice podcast in `../app`.

Design: [docs/specs/2026-09-25-book-translation-pipeline-design.md](docs/specs/2026-09-25-book-translation-pipeline-design.md)

## How it works

1. **Book bible**: reads the whole book once and writes the style guide, a voice
   profile for each speaker, and the recurring terms (added to the Spiritist glossary).
2. **For each chunk** (whole chapters, up to about 2,500 words; 15 chunks):
   - **Translator**: every call has the *entire* Portuguese book as cached context,
     plus the glossary, the voices and the preceding English paragraphs.
   - **Critic**: a rigid doctrinal proofreader looks for secularized Spiritist
     concepts, glossary violations, tone drift and speaker-voice problems.
   - **Refiner**: one pass that fixes the issues the critic found.
3. **Spiritist Book Reviewer**: a senior reviewer of Kardecist literature reads
   the whole Portuguese book and the whole English book side by side and judges
   whether the translation is fit to publish. It writes a report with scores and a
   verdict for each chapter, gives a verdict on every flagged terminology decision,
   and lists concrete findings. It never sees the other agents' reasoning.
4. **Build**: writes `output/Ilana-Book-EN.docx` and checks that the paragraph
   count and speaker highlights match the source.

Progress is saved after every step in `state/global_state.json`. If a run stops,
run the same command again and it continues where it stopped.

## Setup

```bash
cd translation
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # fill in ANTHROPIC_FOUNDRY_API_KEY and ANTHROPIC_FOUNDRY_RESOURCE
```

## Commands

| Command | What it does |
|---|---|
| `.venv/bin/python translate.py run --limit-chunks 1` | Cheap first test: bible + first chunk |
| `.venv/bin/python translate.py run` | Everything: bible → all chunks → book review → build |
| `.venv/bin/python translate.py status` | Progress, open review items, API spend |
| `.venv/bin/python translate.py review` | Run the whole-book Spiritist review again |
| `.venv/bin/python translate.py review --changed` | Re-review only chapters changed since the last review |
| `.venv/bin/python translate.py apply-corrections` | Apply your corrections from the review file |
| `.venv/bin/python translate.py build` | Rebuild the `.docx` from the saved state |

## Reviewing

Read `review/book_review.md` (the reviewer's report) and `review/translation_review.md`.
Make your edits in **`review/translation_review.json`**:

- The term is correct → do nothing.
- The term must change → set `"correction": "the English to use"`.
- Act on a reviewer finding → set `"review_status": "accept"`. Optionally put your
  own wording in `"correction"`.
- Reject a finding → set `"review_status": "rejected"`.

Then run `apply-corrections`. Corrected terms become mandatory glossary entries, and
only the chunks that contain them are re-translated. Accepted findings are applied
to their chunks, and the `.docx` is rebuilt.

## Notes

- Opus 5.5 does not accept `temperature`. Precision comes from `TRANSLATION_EFFORT`
  (default `high`), `REVIEW_EFFORT` (default `xhigh`) and schema-validated JSON output.
- Tests use a fake model and cost nothing: `.venv/bin/python -m pytest tests`.
- The podcast app finds chapters with a `capítulo` pattern (`app/parse_colors.py`).
  For the English book it also needs to match `Chapter`.
