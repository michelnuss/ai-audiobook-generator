"""Orchestrator: runs the agents chunk by chunk, keeps state, feeds the review log."""

import logging

from agents import Agents
from chunker import Chunk, build_chunks
from config import Settings
from docx_io import read_source, verify_output, write_translation
from glossary import Glossary, GlossaryEntry, normalize
from llm import LLM, RefusalError
from prompts import render_book, render_guidance, system_blocks
from review import ReviewLog, render_book_review
from state import (
    CRITIQUED, FAILED, FINAL, NEEDS_REVISION, PENDING, TRANSLATED, StateStore, atomic_write_json,
)

log = logging.getLogger(__name__)

# Claude Opus 5.5 list prices, USD per million tokens (1h cache writes cost 2x input).
PRICE = {"input_tokens": 4.00, "output_tokens": 20.00,
         "cache_read_input_tokens": 0.20, "cache_creation_input_tokens": 8.00}


class Pipeline:
    def __init__(self, settings: Settings, llm: LLM | None, reset: bool = False):
        self.settings = settings
        self.paragraphs = read_source(settings.source_docx)
        self.by_id = {p.id: p for p in self.paragraphs}
        self.order = [p.id for p in self.paragraphs if p.translatable]
        self.source_book = render_book(self.paragraphs)

        if reset:
            for path in (settings.review_json, settings.review_md,
                         settings.book_review_json, settings.book_review_md):
                path.unlink(missing_ok=True)
        self.state = StateStore(settings.state_file)
        self.state.init_source(settings.source_docx, reset=reset)
        if not self.state.data["chunks"]:
            self.state.ensure_chunks(build_chunks(self.paragraphs, settings.max_chunk_words))
        if self.state.data["glossary"] is None:
            self.state.data["glossary"] = Glossary.seeded().to_list()
            self.state.save()
        self.glossary = Glossary.from_list(self.state.data["glossary"])
        self.review = ReviewLog(settings.review_json, settings.review_md)
        self.agents = None
        if llm is not None:
            self.agents = Agents(llm, self.state.add_usage, effort=settings.effort,
                                 review_effort=settings.review_effort,
                                 max_tokens=settings.max_output_tokens)

    # --- helpers -------------------------------------------------------------------------

    def chunks(self) -> list[Chunk]:
        return [Chunk(cid, rec["title"], rec["paragraph_ids"])
                for cid, rec in self.state.data["chunks"].items()]

    def system(self) -> list[dict]:
        return system_blocks(self.source_book, render_guidance(self.glossary, self.state.data["bible"]))

    def _save_glossary(self) -> None:
        self.state.data["glossary"] = self.glossary.to_list()
        self.state.save()

    def preceding_english(self, chunk_id: str) -> list[str]:
        first = self.state.chunk(chunk_id)["paragraph_ids"][0]
        finals = self.state.final_translations()
        before = [finals[pid] for pid in self.order[: self.order.index(first)] if pid in finals]
        return before[-self.settings.context_paragraphs:]

    def chunk_of_paragraph(self) -> dict[str, str]:
        return {pid: c.id for c in self.chunks() for pid in c.paragraph_ids}

    def all_final(self) -> bool:
        return all(rec["status"] == FINAL for rec in self.state.data["chunks"].values())

    # --- stages --------------------------------------------------------------------------

    def run_bible(self, force: bool = False) -> None:
        if self.state.data["bible"] and not force:
            return
        log.info("book bible: reading the whole book")
        bible = self.agents.bible(self.system())
        for term in bible["terms"]:
            self.glossary.add(GlossaryEntry(term["source"], term["target"], term["rationale"], "bible"))
        self.review.add_bible_terms(bible["terms"])
        self.review.save()
        atomic_write_json(self.settings.state_dir / "book_bible.json", bible)
        self.state.data["bible"] = bible
        self._save_glossary()

    def process_chunk(self, chunk_id: str) -> None:
        rec = self.state.chunk(chunk_id)
        paras = [self.by_id[pid] for pid in rec["paragraph_ids"]]
        if rec["status"] == FAILED:
            rec["status"] = rec.pop("failed_stage", PENDING)
        stage = rec["status"]
        try:
            if rec["status"] == PENDING:
                log.info("%s: translating %d paragraphs (%s)", chunk_id, len(paras), rec["title"])
                draft, flags = self.agents.translate(self.system(), paras, self.preceding_english(chunk_id),
                                                     rec.get("reviewer_notes"))
                self.review.supersede_chunk(chunk_id, rec["version"])
                self.review.add_flags(chunk_id, rec["version"], "translator", flags)
                self.review.save()
                rec.update(draft=draft, draft_flags=flags, status=TRANSLATED)
                self.state.save()

            stage = rec["status"]
            if rec["status"] == TRANSLATED:
                log.info("%s: doctrinal critique", chunk_id)
                issues, flags = self.agents.critique(self.system(), paras, rec["draft"], rec.get("draft_flags", []))
                self.review.add_flags(chunk_id, rec["version"], "critic", flags)
                self.review.save()
                rec.update(issues=issues, status=CRITIQUED)
                self.state.save()

            stage = rec["status"]
            if rec["status"] == CRITIQUED:
                final = rec["draft"]
                if rec["issues"]:
                    log.info("%s: refining (%d issues)", chunk_id, len(rec["issues"]))
                    final, flags = self.agents.refine(self.system(), paras, rec["draft"], rec["issues"])
                    self.review.add_flags(chunk_id, rec["version"], "refiner", flags)
                    self.review.save()
                rec.update(final=final, status=FINAL, reviewer_notes=[], error=None)
                self.state.save()

            stage = rec["status"]
            if rec["status"] == NEEDS_REVISION:
                log.info("%s: applying %d reviewer findings", chunk_id, len(rec["issues"]))
                final, flags = self.agents.refine(self.system(), paras, rec["final"], rec["issues"])
                rec["version"] += 1
                self.review.add_flags(chunk_id, rec["version"], "refiner", flags)
                self.review.save()
                rec.update(final=final, status=FINAL, issues=[], error=None)
                self.state.save()
        except RefusalError as exc:
            log.error("%s: %s — skipping this chunk for now", chunk_id, exc)
            rec.update(status=FAILED, failed_stage=stage, error=str(exc))
            self.state.save()

    def run_chunks(self, limit: int | None = None) -> int:
        done = 0
        for chunk_id in self.state.chunk_ids():
            if self.state.chunk(chunk_id)["status"] == FINAL:
                continue
            if limit is not None and done >= limit:
                break
            self.process_chunk(chunk_id)
            done += 1
        return done

    def run_book_review(self, changed_only: bool = False) -> dict | None:
        if not self.all_final():
            raise RuntimeError("the book review needs every chunk translated; run `translate.py run` first")
        reviewed = self.state.data["reviewed_versions"]
        focus = None
        if changed_only:
            focus = [cid for cid, rec in self.state.data["chunks"].items() if reviewed.get(cid) != rec["version"]]
            if not focus:
                log.info("no chunk changed since the last book review")
                return None

        finals = self.state.final_translations()
        chunks_desc = [{"chunk_id": c.id, "title": c.title,
                        "paragraphs": f"{c.paragraph_ids[0]}–{c.paragraph_ids[-1]}"}
                       for c in self.chunks() if focus is None or c.id in focus]
        # Independence: the reviewer sees each decision but never the other agents' reasoning.
        decisions = [
            {"decision_id": e["id"], "paragraph_id": e["paragraph_id"], "original_term": e["original_term"],
             "assigned_translation": e["assigned_translation"], "context_snippet": e["context_snippet"]}
            for e in self.review.open_decisions()
            if focus is None or e["chunk"] in focus or e.get("reviewer") is None
        ]
        log.info("book review: whole book, %d decisions%s", len(decisions),
                 f", focus {', '.join(focus)}" if focus else "")
        result = self.agents.review_book(self.system(), render_book(self.paragraphs, finals),
                                         chunks_desc, decisions, focus)

        round_no = self.state.data.get("review_rounds", 0) + 1
        self.review.apply_book_review(round_no, result, self.chunk_of_paragraph())
        self.review.save()
        titles = {c.id: c.title for c in self.chunks()}
        atomic_write_json(self.settings.review_dir / f"book_review_round{round_no}.json", result)
        atomic_write_json(self.settings.book_review_json, result)
        self.settings.book_review_md.write_text(render_book_review(result, titles), encoding="utf-8")
        self.state.data.update(review_rounds=round_no, book_review_done=True)
        for cid, rec in self.state.data["chunks"].items():
            if focus is None or cid in focus:
                reviewed[cid] = rec["version"]
        self.state.save()
        return result

    def apply_corrections(self) -> tuple[int, int, list[str]]:
        """Apply the human reviewer's corrections; returns (terms, findings, affected chunks)."""
        self.review.reload()
        corrections = self.review.term_corrections()
        findings = self.review.accepted_findings()
        if not corrections and not findings:
            return 0, 0, []

        retranslate: set[str] = set()
        notes: dict[str, list[str]] = {}
        for entry in corrections:
            term, new = entry["original_term"], entry["correction"].strip()
            self.glossary.add(GlossaryEntry(term, new, f"Human reviewer decision ({entry['id']}).", "reviewer"))
            wanted = normalize(term)
            for chunk in self.chunks():
                if chunk.id == entry["chunk"] or any(
                        wanted in normalize(self.by_id[pid].text) for pid in chunk.paragraph_ids):
                    retranslate.add(chunk.id)
                    notes.setdefault(chunk.id, []).append(
                        f"Translate '{term}' as '{new}' (human reviewer decision).")
        self._save_glossary()

        for cid in sorted(retranslate):
            self.state.restart_chunk(cid, notes[cid])
        for entry in findings:
            issue = {"paragraph_id": ", ".join(entry["paragraph_ids"]), "severity": entry["severity"],
                     "category": entry["category"], "problem": entry["problem"],
                     "suggested_fix": entry.get("correction") or entry["suggested_revision"]}
            for cid in entry["chunks"]:
                self.state.request_revision(cid, [issue])

        self.review.mark(corrections + findings, "applied")
        self.review.save()
        affected = sorted(retranslate | {c for f in findings for c in f["chunks"]})
        self.run_chunks()
        return len(corrections), len(findings), affected

    def build(self) -> list[str]:
        report = write_translation(self.settings.source_docx, self.settings.output_docx,
                                   self.state.final_translations())
        problems = verify_output(self.settings.source_docx, self.settings.output_docx)
        lines = [f"Wrote {self.settings.output_docx} — {report.translated} paragraphs translated."]
        if report.kept_source:
            lines.append(f"{len(report.kept_source)} paragraphs not translated yet (kept in Portuguese).")
        if report.markup_dropped:
            lines.append("Bold markup unbalanced, written without inline bold: " + ", ".join(report.markup_dropped))
        lines += [f"CHECK FAILED: {p}" for p in problems] or ["Check passed: paragraph count and speaker highlights match the source."]
        return lines

    # --- status --------------------------------------------------------------------------

    def status_lines(self) -> list[str]:
        lines = ["Chunk  Status          Ver  Title"]
        for cid, rec in self.state.data["chunks"].items():
            extra = f"  ({rec['error']})" if rec.get("error") else ""
            lines.append(f"{cid:<6} {rec['status']:<15} {rec['version']:<4} {rec['title']}{extra}")
        usage = self.state.data["usage"]
        cost = sum(usage[k] * PRICE[k] for k in PRICE) / 1_000_000
        lines += [
            "",
            f"Book bible: {'done' if self.state.data['bible'] else 'not yet'} · "
            f"Book review rounds: {self.state.data.get('review_rounds', 0)} · "
            f"Glossary terms: {len(self.glossary)}",
            f"Review log: {len(self.review.open_decisions())} open decisions, "
            f"{sum(1 for e in self.review.entries if e['kind'] == 'finding' and e['review_status'] == 'pending')} "
            "pending findings",
            f"API: {usage['calls']} calls · input {usage['input_tokens']:,} · cache read "
            f"{usage['cache_read_input_tokens']:,} · cache write {usage['cache_creation_input_tokens']:,} · "
            f"output {usage['output_tokens']:,} · ≈ ${cost:,.2f}",
        ]
        return lines
