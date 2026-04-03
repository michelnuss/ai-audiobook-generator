"""Parse a .docx file and split it into chapters."""

import re
from dataclasses import dataclass
from docx import Document

CHAPTER_PATTERN = re.compile(r"capítulo\s+\d+", re.IGNORECASE)
HEADING_STYLES = {"Heading 1", "Heading 2", "Title", "Título", "Heading1", "Heading2"}
CHARS_PER_PAGE = 1800


@dataclass
class Chapter:
    index: int
    title: str
    body: str
    page_start: int
    page_end: int
    char_count: int


def _is_chapter_heading(paragraph) -> str | None:
    """Return the matched chapter string if the paragraph is a chapter heading, else None."""
    text = paragraph.text.strip()
    if not text:
        return None

    # Check style-based headings
    style_name = paragraph.style.name if paragraph.style else ""
    is_heading_style = style_name in HEADING_STYLES

    # Check if text matches chapter pattern
    match = CHAPTER_PATTERN.match(text)
    if match:
        return text

    # Also check heading-styled paragraphs that contain the pattern anywhere
    if is_heading_style and CHAPTER_PATTERN.search(text):
        return text

    return None


def parse_docx(path: str) -> list[Chapter]:
    """Parse the docx at *path* and return an ordered list of Chapter objects."""
    doc = Document(path)

    # Collect (title, [paragraph_texts]) groups
    raw_chapters: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_paragraphs: list[str] = []
    preface_paragraphs: list[str] = []

    for para in doc.paragraphs:
        heading = _is_chapter_heading(para)
        if heading:
            if current_title is not None:
                raw_chapters.append((current_title, current_paragraphs))
            current_title = heading
            current_paragraphs = []
        elif current_title is not None:
            text = para.text.strip()
            if text:
                current_paragraphs.append(text)
        else:
            text = para.text.strip()
            if text:
                preface_paragraphs.append(text)

    # Don't forget the last chapter
    if current_title is not None:
        raw_chapters.append((current_title, current_paragraphs))

    # Prepend preface as first entry if there was meaningful text before chapter 1
    if preface_paragraphs:
        raw_chapters.insert(0, ("Prefácio", preface_paragraphs))

    # Deduplicate: if the same chapter title appears more than once, keep the
    # last occurrence (assumed to be the most revised version).
    seen: dict[str, int] = {}
    for i, (title, _) in enumerate(raw_chapters):
        key = re.sub(r"\s+", " ", title.strip().lower())
        seen[key] = i
    raw_chapters = [raw_chapters[i] for i in sorted(seen.values())]

    # Build Chapter objects with estimated page ranges
    chapters: list[Chapter] = []
    cumulative_chars = 0

    for idx, (title, paragraphs) in enumerate(raw_chapters):
        body = "\n\n".join(paragraphs)
        char_count = len(body)
        page_start = cumulative_chars // CHARS_PER_PAGE + 1
        cumulative_chars += char_count
        page_end = max(page_start, (cumulative_chars - 1) // CHARS_PER_PAGE + 1)

        chapters.append(Chapter(
            index=idx,
            title=title,
            body=body,
            page_start=page_start,
            page_end=page_end,
            char_count=char_count,
        ))

    return chapters


if __name__ == "__main__":
    import sys
    import os

    docx_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not docx_path:
        # Try to find the .docx next to this script or one level up
        for candidate in [
            os.path.join(os.path.dirname(__file__), "..", "*.docx"),
        ]:
            import glob
            matches = glob.glob(candidate)
            if matches:
                docx_path = matches[0]
                break

    if not docx_path or not os.path.exists(docx_path):
        print("Uso: python3 parser.py caminho/para/o/livro.docx")
        sys.exit(1)

    chapters = parse_docx(docx_path)
    print(f"\nTotal de capítulos: {len(chapters)}\n")
    print(f"{'#':<4} {'Título':<55} {'Páginas':<12} {'Chars'}")
    print("-" * 85)
    for ch in chapters:
        print(f"{ch.index:<4} {ch.title:<55} p.{ch.page_start}-{ch.page_end:<8} {ch.char_count}")
