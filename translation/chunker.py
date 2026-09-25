"""Group translatable paragraphs into chunks.

Chapters ("Capítulo N:", "Prefácio", "Posfácio") are kept whole and packed
together up to `max_words`; a chapter larger than that is split at paragraph
boundaries.
"""

import re
from dataclasses import dataclass

from docx_io import SourceParagraph

SECTION_HEADING = re.compile(r"^(cap[ií]tulo\s+\d+|pref[aá]cio|p[oó]s-?f[aá]cio)", re.IGNORECASE)


@dataclass
class Chunk:
    id: str
    title: str
    paragraph_ids: list[str]


@dataclass
class Section:
    title: str
    paragraphs: list[SourceParagraph]

    @property
    def words(self) -> int:
        return sum(len(p.text.split()) for p in self.paragraphs)


def is_section_heading(text: str) -> bool:
    return len(text) <= 150 and bool(SECTION_HEADING.match(text.strip()))


def split_sections(paragraphs: list[SourceParagraph]) -> list[Section]:
    sections = [Section("Front matter", [])]
    for para in paragraphs:
        if not para.translatable:
            continue
        if is_section_heading(para.text.replace("**", "")):
            sections.append(Section(para.text.replace("**", "").strip(), []))
        sections[-1].paragraphs.append(para)
    return [s for s in sections if s.paragraphs]


def _split_large(section: Section, max_words: int) -> list[Section]:
    parts: list[Section] = []
    current: list[SourceParagraph] = []
    words = 0
    for para in section.paragraphs:
        n = len(para.text.split())
        if current and words + n > max_words:
            parts.append(Section(f"{section.title} (part {len(parts) + 1})", current))
            current, words = [], 0
        current.append(para)
        words += n
    if current:
        title = f"{section.title} (part {len(parts) + 1})" if parts else section.title
        parts.append(Section(title, current))
    return parts


def build_chunks(paragraphs: list[SourceParagraph], max_words: int = 2500) -> list[Chunk]:
    units: list[Section] = []
    for section in split_sections(paragraphs):
        units.extend(_split_large(section, max_words) if section.words > max_words else [section])

    groups: list[list[Section]] = []
    for unit in units:
        if groups and sum(s.words for s in groups[-1]) + unit.words <= max_words:
            groups[-1].append(unit)
        else:
            groups.append([unit])

    chunks = []
    for n, group in enumerate(groups, start=1):
        title = group[0].title if len(group) == 1 else f"{group[0].title} … {group[-1].title}"
        ids = [p.id for s in group for p in s.paragraphs]
        chunks.append(Chunk(id=f"c{n:02d}", title=title, paragraph_ids=ids))
    return chunks
