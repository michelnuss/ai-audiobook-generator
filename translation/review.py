"""Human-in-the-loop review log.

translation_review.json is the source of truth and the file the human reviewer edits.
translation_review.md is regenerated from it for reading.

Entry kinds:
  decision — a terminology/judgment call flagged by the bible, translator, critic or
             refiner; carries the book reviewer's verdict once the book is reviewed.
  finding  — a problem found by the whole-book Spiritist reviewer.

Reviewer workflow:
  decision correct            → nothing to do (optionally review_status = "approved")
  decision must change        → set "correction" to the English term to use
  finding to act on           → set review_status = "accept" (optionally "correction"
                                with the wording you want)
  finding / decision rejected → review_status = "rejected"
then run `python translate.py apply-corrections`.
"""

import json
from pathlib import Path

from state import atomic_write_json

CLOSED = {"applied", "rejected", "superseded"}
SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}


class ReviewLog:
    def __init__(self, json_path: Path, md_path: Path):
        self.json_path = json_path
        self.md_path = md_path
        self.entries: list[dict] = (
            json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else []
        )

    def reload(self) -> None:
        """Re-read the JSON, picking up edits the human made while the pipeline was idle."""
        if self.json_path.exists():
            self.entries = json.loads(self.json_path.read_text(encoding="utf-8"))

    def save(self) -> None:
        atomic_write_json(self.json_path, self.entries)
        self.md_path.write_text(self.render_markdown(), encoding="utf-8")

    def _next_id(self) -> str:
        return f"R{len(self.entries) + 1:04d}"

    def _has_key(self, key: str) -> bool:
        return any(e.get("origin_key") == key for e in self.entries)

    def by_id(self, entry_id: str) -> dict | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    # --- adding entries --------------------------------------------------------------

    def add_flags(self, chunk_id: str | None, version: int, source: str, flags: list[dict]) -> int:
        """Add flagged decisions once per (chunk, version, source) — safe to call again on resume."""
        key = f"{chunk_id}:{version}:{source}"
        if self._has_key(key):
            return 0
        for flag in flags:
            self.entries.append({
                "id": self._next_id(),
                "kind": "decision",
                "source": source,
                "origin_key": key,
                "chunk": chunk_id,
                "chunk_version": version,
                "paragraph_id": flag.get("paragraph_id", ""),
                "original_term": flag["original_term"],
                "assigned_translation": flag["assigned_translation"],
                "context_snippet": flag.get("context_snippet", ""),
                "ai_reasoning": flag.get("ai_reasoning", ""),
                "reviewer": None,
                "review_status": "pending",
                "correction": None,
            })
        return len(flags)

    def add_bible_terms(self, terms: list[dict]) -> int:
        flags = [{"original_term": t["source"], "assigned_translation": t["target"],
                  "ai_reasoning": t["rationale"]} for t in terms]
        return self.add_flags(None, 1, "bible", flags)

    def supersede_chunk(self, chunk_id: str, current_version: int) -> None:
        """Pending flags from older versions of a re-translated chunk no longer apply."""
        for e in self.entries:
            if (e["kind"] == "decision" and e["chunk"] == chunk_id
                    and e["chunk_version"] < current_version and e["review_status"] == "pending"):
                e["review_status"] = "superseded"

    def apply_book_review(self, round_no: int, review: dict, chunk_of: dict[str, str]) -> None:
        for verdict in review.get("decision_verdicts", []):
            entry = self.by_id(verdict["decision_id"])
            if entry is not None:
                entry["reviewer"] = {
                    "verdict": verdict["verdict"],
                    "preferred_translation": verdict["preferred_translation"] or None,
                    "rationale": verdict["rationale"],
                }
        key = f"book_review:{round_no}"
        if self._has_key(key):
            return
        for finding in review.get("findings", []):
            chunks = sorted({chunk_of[p] for p in finding["paragraph_ids"] if p in chunk_of})
            self.entries.append({
                "id": self._next_id(),
                "kind": "finding",
                "source": "book_reviewer",
                "origin_key": key,
                "chunks": chunks,
                "paragraph_ids": finding["paragraph_ids"],
                "category": finding["category"],
                "severity": finding["severity"],
                "problem": finding["problem"],
                "suggested_revision": finding["suggested_revision"],
                "review_status": "pending",
                "correction": None,
            })

    # --- queries -----------------------------------------------------------------------

    def open_decisions(self) -> list[dict]:
        return [e for e in self.entries if e["kind"] == "decision" and e["review_status"] not in CLOSED]

    def term_corrections(self) -> list[dict]:
        return [e for e in self.open_decisions() if e.get("correction")]

    def accepted_findings(self) -> list[dict]:
        return [e for e in self.entries if e["kind"] == "finding" and e["review_status"] == "accept"]

    def mark(self, entries: list[dict], status: str) -> None:
        for e in entries:
            e["review_status"] = status

    # --- markdown ----------------------------------------------------------------------

    def render_markdown(self) -> str:
        decisions = self.open_decisions()
        disagreements = [e for e in decisions if (e.get("reviewer") or {}).get("verdict") == "disagree"]
        uncertain = [e for e in decisions if (e.get("reviewer") or {}).get("verdict") == "uncertain"]
        others = [e for e in decisions if e not in disagreements and e not in uncertain]
        findings = sorted(
            (e for e in self.entries if e["kind"] == "finding" and e["review_status"] not in CLOSED),
            key=lambda e: SEVERITY_ORDER.get(e["severity"], 3),
        )

        out = [
            "# Translation review",
            "",
            "Edit `translation_review.json` (this file is regenerated). For each entry:",
            "",
            "- **Correct** → nothing to do.",
            "- **Decision to change** → set `\"correction\"` to the English to use.",
            "- **Finding to act on** → set `\"review_status\": \"accept\"` "
            "(optionally `\"correction\"` with your wording). Reject with `\"rejected\"`.",
            "",
            "Then run `python translate.py apply-corrections`.",
            "",
            f"Open: {len(findings)} reviewer findings · {len(disagreements)} reviewer disagreements · "
            f"{len(uncertain)} uncertain · {len(others)} other decisions",
            "",
        ]

        if findings:
            out += ["## Findings from the Spiritist book reviewer", ""]
            for e in findings:
                out += [
                    f"### {e['id']} — {e['severity']} · {e['category']} · {', '.join(e['paragraph_ids'])}",
                    "",
                    f"**Problem:** {e['problem']}",
                    "",
                    f"**Suggested revision:** {e['suggested_revision']}",
                    "",
                ]

        for title, group in (("Reviewer disagrees", disagreements),
                             ("Reviewer uncertain", uncertain),
                             ("Other flagged decisions", others)):
            if not group:
                continue
            out += [f"## {title}", "",
                    "| ID | Chunk | Portuguese | Translation used | Reviewer | Context | Reasoning |",
                    "|---|---|---|---|---|---|---|"]
            for e in group:
                rv = e.get("reviewer") or {}
                reviewer = ""
                if rv:
                    reviewer = rv["verdict"]
                    if rv.get("preferred_translation"):
                        reviewer += f" → *{rv['preferred_translation']}*"
                    reviewer += f": {rv['rationale']}"
                out.append("| " + " | ".join(_cell(x) for x in (
                    e["id"], e["chunk"] or "bible", e["original_term"], e["assigned_translation"],
                    reviewer, e["context_snippet"], e["ai_reasoning"])) + " |")
            out.append("")
        return "\n".join(out)


def _cell(value) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


VERDICT_LABELS = {
    "fit_for_publication": "Fit for publication",
    "fit_after_revisions": "Fit after revisions",
    "not_fit": "Not fit for publication",
}


def render_book_review(review: dict, chunk_titles: dict[str, str]) -> str:
    out = [
        "# Spiritist book review — English translation",
        "",
        f"**Verdict: {VERDICT_LABELS.get(review['overall_verdict'], review['overall_verdict'])}**",
        "",
        review["report"],
        "",
        "## Scores",
        "",
        "| Dimension | Score | Commentary |",
        "|---|---|---|",
    ]
    for s in review.get("scores", []):
        out.append(f"| {s['dimension'].replace('_', ' ')} | {s['score']}/5 | {_cell(s['commentary'])} |")
    out += ["", "## Chapters", "", "| Chunk | Title | Verdict | Notes |", "|---|---|---|---|"]
    for c in review.get("chapters", []):
        out.append(f"| {c['chunk_id']} | {_cell(chunk_titles.get(c['chunk_id'], ''))} | "
                   f"{c['verdict']} | {_cell(c['notes'])} |")
    counts: dict[str, int] = {}
    for f in review.get("findings", []):
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    out += ["", f"Findings: {counts or 'none'} — see translation_review.md.", ""]
    return "\n".join(out)
