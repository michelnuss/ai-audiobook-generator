"""Settings for the translation pipeline, loaded from translation/.env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_SOURCE = "Ilana-Livro-LIMPO colorido (1).docx"
DEFAULT_OUTPUT = "output/Ilana-Book-EN.docx"


@dataclass(frozen=True)
class Settings:
    source_docx: Path
    output_docx: Path
    state_dir: Path
    review_dir: Path
    model: str
    effort: str
    review_effort: str
    max_chunk_words: int
    context_paragraphs: int
    max_output_tokens: int

    @property
    def state_file(self) -> Path:
        return self.state_dir / "global_state.json"

    @property
    def review_json(self) -> Path:
        return self.review_dir / "translation_review.json"

    @property
    def review_md(self) -> Path:
        return self.review_dir / "translation_review.md"

    @property
    def book_review_json(self) -> Path:
        return self.review_dir / "book_review.json"

    @property
    def book_review_md(self) -> Path:
        return self.review_dir / "book_review.md"


def _path(env_name: str, default: str) -> Path:
    value = Path(os.getenv(env_name) or default)
    return value if value.is_absolute() else ROOT / value


def load_settings() -> Settings:
    return Settings(
        source_docx=_path("SOURCE_DOCX", DEFAULT_SOURCE),
        output_docx=_path("OUTPUT_DOCX", DEFAULT_OUTPUT),
        state_dir=_path("STATE_DIR", "state"),
        review_dir=_path("REVIEW_DIR", "review"),
        model=os.getenv("TRANSLATION_MODEL") or "claude-opus-5-5",
        effort=os.getenv("TRANSLATION_EFFORT") or "high",
        review_effort=os.getenv("REVIEW_EFFORT") or "xhigh",
        max_chunk_words=int(os.getenv("MAX_CHUNK_WORDS") or 2500),
        context_paragraphs=int(os.getenv("CONTEXT_PARAGRAPHS") or 40),
        max_output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS") or 64000),
    )


class ConfigError(RuntimeError):
    pass


def require_credentials() -> None:
    """Fail fast before any API call if the Azure/Foundry settings are blank."""
    missing = []
    if not os.getenv("ANTHROPIC_FOUNDRY_API_KEY"):
        missing.append("ANTHROPIC_FOUNDRY_API_KEY")
    if not (os.getenv("ANTHROPIC_FOUNDRY_RESOURCE") or os.getenv("ANTHROPIC_FOUNDRY_BASE_URL")):
        missing.append("ANTHROPIC_FOUNDRY_RESOURCE (or ANTHROPIC_FOUNDRY_BASE_URL)")
    if missing:
        raise ConfigError(
            "Missing settings in translation/.env: " + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
