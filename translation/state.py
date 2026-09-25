"""global_state.json: everything needed to resume the pipeline where it stopped."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

# Chunk stages, in order. A chunk resumes from the stage after its current status.
PENDING, TRANSLATED, CRITIQUED, FINAL, FAILED, NEEDS_REVISION = (
    "pending", "translated", "critiqued", "final", "failed", "needs_revision",
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class SourceChangedError(RuntimeError):
    pass


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    def init_source(self, source: Path, reset: bool = False) -> None:
        digest = file_sha256(source)
        if reset or not self.data:
            self.data = {
                "source_file": source.name,
                "source_sha256": digest,
                "bible": None,
                "glossary": None,
                "chunks": {},
                "book_review_done": False,
                "reviewed_versions": {},
                "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            }
            self.save()
        elif self.data.get("source_sha256") != digest:
            raise SourceChangedError(
                f"{source.name} changed since this translation started. "
                "Run with --reset to start over (this discards the saved translation)."
            )

    # --- chunks -------------------------------------------------------------------

    def ensure_chunks(self, chunks) -> None:
        for chunk in chunks:
            self.data["chunks"].setdefault(chunk.id, {
                "title": chunk.title,
                "paragraph_ids": chunk.paragraph_ids,
                "status": PENDING,
                "version": 1,
                "draft": None,
                "issues": [],
                "final": None,
                "reviewer_notes": [],
                "error": None,
            })
        self.save()

    def chunk(self, chunk_id: str) -> dict:
        return self.data["chunks"][chunk_id]

    def chunk_ids(self) -> list[str]:
        return list(self.data["chunks"].keys())

    def final_translations(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for record in self.data["chunks"].values():
            if record.get("final"):
                merged.update(record["final"])
        return merged

    def restart_chunk(self, chunk_id: str, reviewer_notes: list[str] | None = None) -> None:
        """Queue a chunk for full re-translation (e.g. after a glossary correction)."""
        record = self.chunk(chunk_id)
        record.update(status=PENDING, draft=None, issues=[], error=None,
                      version=record["version"] + 1)
        if reviewer_notes:
            record["reviewer_notes"] = record.get("reviewer_notes", []) + reviewer_notes
        self.save()

    def request_revision(self, chunk_id: str, issues: list[dict]) -> None:
        """Queue reviewer findings to be applied to the chunk's current final text."""
        record = self.chunk(chunk_id)
        if record["status"] == PENDING:
            record["reviewer_notes"] = record.get("reviewer_notes", []) + [
                f"{i['paragraph_id']}: {i['problem']} Use: {i['suggested_fix']}" for i in issues]
        else:
            queued = record["issues"] if record["status"] == NEEDS_REVISION else []
            record.update(status=NEEDS_REVISION, issues=queued + issues)
        self.save()

    # --- usage --------------------------------------------------------------------

    def add_usage(self, usage: dict) -> None:
        totals = self.data["usage"]
        totals["calls"] += 1
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            totals[key] += usage.get(key) or 0
