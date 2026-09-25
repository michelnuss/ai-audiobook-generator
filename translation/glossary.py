"""Spiritist glossary: seed terms, terms proposed by the book bible, reviewer corrections.

Precedence when the same source term appears more than once:
reviewer correction > seed > book bible.
"""

import unicodedata
from dataclasses import asdict, dataclass

PRECEDENCE = {"bible": 1, "seed": 2, "reviewer": 3}


@dataclass
class GlossaryEntry:
    source: str
    target: str
    note: str = ""
    origin: str = "seed"  # seed | bible | reviewer


SEED_GLOSSARY = [
    GlossaryEntry("Desencarne / Desencarnação", "discarnation", "Never translate as 'death'."),
    GlossaryEntry("desencarnar / desencarnado", "to discarnate / discarnate (n., adj.)",
                  "A discarnate is a Spirit without a physical body; never 'dead person'."),
    GlossaryEntry("encarnado / encarnação", "incarnate / incarnation"),
    GlossaryEntry("Reencarnação", "reincarnation"),
    GlossaryEntry("Perispírito", "perispirit", "The semi-material envelope of the Spirit (Kardec)."),
    GlossaryEntry("Obsessão", "obsession", "Technical Spiritist sense: persistent influence of a Spirit."),
    GlossaryEntry("Subjugação", "subjugation", "Kardec's most severe degree of obsession."),
    GlossaryEntry("Fascinação", "fascination", "Kardec's intermediate degree of obsession."),
    GlossaryEntry("Fluido Cósmico Universal", "Universal Cosmic Fluid"),
    GlossaryEntry("fluido / fluidos", "fluid / fluids",
                  "Spiritist sense (subtle matter/energy). Flag contexts where the sense is ambiguous."),
    GlossaryEntry("Erraticidade", "erraticity", "State of Spirits between incarnations."),
    GlossaryEntry("Espírito errante", "errant Spirit", "Not 'wandering ghost'."),
    GlossaryEntry("Espírito (a entidade)", "Spirit (capitalized)", "Capitalize when it refers to the being."),
    GlossaryEntry("Passe", "passe (spiritual healing)",
                  "Keep 'passe' in the text; gloss as '(spiritual healing)' on first use in the book."),
    GlossaryEntry("Plano Espiritual", "Spiritual Realm"),
    GlossaryEntry("Plano material / plano físico", "material plane / physical plane"),
    GlossaryEntry("Umbral", "Umbral (the Threshold)", "Keep 'Umbral'; gloss '(the Threshold)' on first use."),
    GlossaryEntry("Mediunidade / Médium", "mediumship / medium", "Never 'witchcraft', 'psychic power' or 'channeling'."),
    GlossaryEntry("Espiritismo / Espírita", "Spiritism / Spiritist",
                  "Never 'spiritualism' / 'spiritualist' (a different movement)."),
    GlossaryEntry("Codificação", "the Codification", "Kardec's five foundational works."),
    GlossaryEntry("Lei de Causa e Efeito", "Law of Cause and Effect"),
    GlossaryEntry("Mentor / Mentor espiritual", "mentor / spiritual mentor"),
    GlossaryEntry("Evangelho", "the Gospel"),
]


def normalize(term: str) -> str:
    decomposed = unicodedata.normalize("NFKD", term)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


class Glossary:
    def __init__(self, entries: list[GlossaryEntry] | None = None):
        self._entries: dict[str, GlossaryEntry] = {}
        for entry in entries or []:
            self.add(entry)

    @classmethod
    def seeded(cls) -> "Glossary":
        return cls([GlossaryEntry(**asdict(e)) for e in SEED_GLOSSARY])

    @classmethod
    def from_list(cls, items: list[dict]) -> "Glossary":
        return cls([GlossaryEntry(**item) for item in items])

    def to_list(self) -> list[dict]:
        return [asdict(e) for e in self._entries.values()]

    def add(self, entry: GlossaryEntry) -> bool:
        """Add or replace an entry; returns False if a higher-precedence entry already exists."""
        key = normalize(entry.source)
        existing = self._entries.get(key)
        if existing and PRECEDENCE[existing.origin] > PRECEDENCE[entry.origin]:
            return False
        self._entries[key] = entry
        return True

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):
        return iter(self._entries.values())

    def render(self) -> str:
        """Glossary as a Markdown table for prompts; sorted so the cached prompt is stable."""
        lines = ["| Portuguese | English (required) | Notes |", "|---|---|---|"]
        for entry in sorted(self._entries.values(), key=lambda e: (-PRECEDENCE[e.origin], normalize(e.source))):
            note = entry.note
            if entry.origin == "reviewer":
                note = ("HUMAN REVIEWER DECISION — mandatory. " + note).strip()
            lines.append(f"| {entry.source} | {entry.target} | {note} |")
        return "\n".join(lines)
