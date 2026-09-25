"""The agents: book bible, translator, critic, refiner and whole-book Spiritist reviewer."""

import json
import logging
from typing import Callable

import prompts
from docx_io import SourceParagraph
from llm import LLM, OutputTruncatedError

log = logging.getLogger(__name__)


class TranslationValidationError(ValueError):
    pass


def validate_translations(expected_ids: list[str], data: dict) -> dict[str, str]:
    """Every expected id exactly once, no unknown ids, no empty text."""
    expected = set(expected_ids)
    result: dict[str, str] = {}
    errors = []
    for item in data.get("translations", []):
        pid, text = item.get("id"), (item.get("text") or "").strip()
        if pid not in expected:
            errors.append(f"unknown paragraph id {pid!r}")
        elif pid in result:
            errors.append(f"paragraph {pid} returned twice")
        elif not text:
            errors.append(f"paragraph {pid} has empty text")
        else:
            result[pid] = text
    missing = [pid for pid in expected_ids if pid not in result]
    if missing:
        errors.append("missing paragraph ids: " + ", ".join(missing))
    if errors:
        raise TranslationValidationError("; ".join(errors))
    return result


def _preceding(english: list[str]) -> str:
    return "\n\n".join(english) if english else "(start of the book)"


class Agents:
    def __init__(self, llm: LLM, on_usage: Callable[[dict], None], *, effort: str,
                 review_effort: str, max_tokens: int, attempts: int = 3):
        self.llm = llm
        self.on_usage = on_usage
        self.effort = effort
        self.review_effort = review_effort
        self.max_tokens = max_tokens
        self.attempts = attempts

    def _call(self, system: list[dict], user: str, schema: dict, effort: str | None = None) -> dict:
        result = self.llm.complete_json(system=system, user=user, schema=schema,
                                        effort=effort or self.effort, max_tokens=self.max_tokens)
        self.on_usage(result.usage)
        return result.data

    def _translation_call(self, system: list[dict], user: str, ids: list[str]) -> tuple[dict[str, str], list[dict]]:
        prompt = user
        for attempt in range(1, self.attempts + 1):
            data = self._call(system, prompt, prompts.TRANSLATION_SCHEMA)
            try:
                return validate_translations(ids, data), data.get("flags", [])
            except TranslationValidationError as exc:
                log.warning("invalid translation (attempt %d/%d): %s", attempt, self.attempts, exc)
                if attempt == self.attempts:
                    raise
                prompt = user + prompts.VALIDATION_RETRY.format(error=exc)
        raise AssertionError("unreachable")

    # --- agents -------------------------------------------------------------------

    def bible(self, system: list[dict]) -> dict:
        return self._call(system, prompts.BIBLE_TASK, prompts.BIBLE_SCHEMA)

    def translate(self, system: list[dict], paragraphs: list[SourceParagraph],
                  preceding_english: list[str], reviewer_notes: list[str] | None = None
                  ) -> tuple[dict[str, str], list[dict]]:
        notes = ""
        if reviewer_notes:
            notes = prompts.REVIEWER_NOTES_BLOCK.format(notes="\n".join(f"- {n}" for n in reviewer_notes))
        user = prompts.TRANSLATOR_TASK.format(
            flag_instructions=prompts.FLAG_INSTRUCTIONS,
            reviewer_notes=notes,
            preceding_english=_preceding(preceding_english),
            chunk=prompts.chunk_payload(paragraphs),
        )
        ids = [p.id for p in paragraphs]
        try:
            return self._translation_call(system, user, ids)
        except OutputTruncatedError:
            if len(paragraphs) < 2:
                raise
            log.warning("answer too long for %d paragraphs; splitting in half", len(paragraphs))
            half = len(paragraphs) // 2
            first, flags1 = self.translate(system, paragraphs[:half], preceding_english, reviewer_notes)
            context = preceding_english + [first[p.id] for p in paragraphs[:half]]
            second, flags2 = self.translate(system, paragraphs[half:], context, reviewer_notes)
            return {**first, **second}, flags1 + flags2

    def critique(self, system: list[dict], paragraphs: list[SourceParagraph], draft: dict[str, str],
                 flags: list[dict]) -> tuple[list[dict], list[dict]]:
        ids = [p.id for p in paragraphs]
        user = prompts.CRITIC_TASK.format(
            flag_instructions=prompts.FLAG_INSTRUCTIONS,
            chunk=prompts.chunk_payload(paragraphs),
            draft=prompts.translations_payload(draft, ids),
            flags=json.dumps([{k: f[k] for k in ("paragraph_id", "original_term", "assigned_translation")}
                              for f in flags], ensure_ascii=False, indent=1),
        )
        data = self._call(system, user, prompts.CRITIQUE_SCHEMA)
        return data.get("issues", []), data.get("flags", [])

    def refine(self, system: list[dict], paragraphs: list[SourceParagraph], draft: dict[str, str],
               issues: list[dict]) -> tuple[dict[str, str], list[dict]]:
        ids = [p.id for p in paragraphs]
        user = prompts.REFINER_TASK.format(
            flag_instructions=prompts.FLAG_INSTRUCTIONS,
            chunk=prompts.chunk_payload(paragraphs),
            draft=prompts.translations_payload(draft, ids),
            issues=json.dumps(issues, ensure_ascii=False, indent=1),
        )
        return self._translation_call(system, user, ids)

    def review_book(self, system: list[dict], english_book: str, chunks: list[dict],
                    decisions: list[dict], focus: list[str] | None = None) -> dict:
        focus_note = ""
        if focus:
            focus_note = (" — this is a re-review after revisions; give chapter entries and "
                          "findings only for chunks " + ", ".join(focus) + ", still judging them "
                          "against the whole book")
        user = prompts.BOOK_REVIEWER_TASK.format(
            focus_note=focus_note,
            chunks=json.dumps(chunks, ensure_ascii=False, indent=1),
            decisions=json.dumps(decisions, ensure_ascii=False, indent=1),
            english_book=english_book,
        )
        data = self._call(system, user, prompts.BOOK_REVIEW_SCHEMA, effort=self.review_effort)
        for score in data.get("scores", []):
            score["score"] = min(5, max(1, int(score["score"])))
        return data
