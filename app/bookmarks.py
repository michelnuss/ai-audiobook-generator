"""Read and write bookmarks to a JSON file."""

import json
from pathlib import Path

BOOKMARKS_FILE = Path(__file__).parent / "bookmarks.json"


def _load() -> list[dict]:
    if not BOOKMARKS_FILE.exists():
        return []
    return json.loads(BOOKMARKS_FILE.read_text(encoding="utf-8"))


def _save(bookmarks: list[dict]) -> None:
    BOOKMARKS_FILE.write_text(
        json.dumps(bookmarks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_bookmarks() -> list[dict]:
    return _load()


def add_bookmark(chapter_index: int, chapter_title: str, sentence_index: int, sentence_text: str) -> dict:
    bookmarks = _load()
    bookmark = {
        "chapter_index": chapter_index,
        "chapter_title": chapter_title,
        "sentence_index": sentence_index,
        "sentence_text": sentence_text[:120],
    }
    bookmarks.append(bookmark)
    _save(bookmarks)
    return bookmark
