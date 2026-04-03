"""FastAPI backend for the audiobook app."""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from parser import parse_docx
from bookmarks import get_bookmarks, add_bookmark
from tts import (
    effective_tts_provider,
    reset_elevenlabs_exhausted,
    synthesize_to_bytes,
    synthesize_with_fallback,
)

load_dotenv(Path(__file__).parent / ".env")

TTS_PROVIDER = os.getenv("TTS_PROVIDER", "azure").lower()
TTS_FALLBACK_TO_AZURE = os.getenv("TTS_FALLBACK_TO_AZURE", "true").lower() in (
    "1",
    "true",
    "yes",
)
AZURE_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_REGION = os.getenv("AZURE_SPEECH_REGION", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "GIuLCSVfgJaUuh7hYOY8")
ELEVENLABS_ET_VOICE_ID = os.getenv("ELEVENLABS_ET_VOICE_ID", "")
ELEVENLABS_BARUCK_VOICE_ID = os.getenv("ELEVENLABS_BARUCK_VOICE_ID", "")
DOCX_PATH = os.getenv("DOCX_PATH", "")

SPEAKER_TAGS_FILE = Path(__file__).parent / "speaker_tags.json"

app = FastAPI(title="Audiolivro")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Parse the book once at startup
chapters = []
speaker_tags: dict = {}

@app.on_event("startup")
def load_book():
    global chapters, speaker_tags
    reset_elevenlabs_exhausted()
    if not DOCX_PATH or not Path(DOCX_PATH).exists():
        print(f"AVISO: Arquivo .docx não encontrado em '{DOCX_PATH}'. Verifique o .env.")
        return
    chapters = parse_docx(DOCX_PATH)
    print(f"Livro carregado: {len(chapters)} capítulos encontrados.")
    if SPEAKER_TAGS_FILE.exists():
        speaker_tags = json.loads(SPEAKER_TAGS_FILE.read_text(encoding="utf-8"))
        print(f"Speaker tags carregados: {len(speaker_tags)} capítulos mapeados.")
    else:
        print("speaker_tags.json não encontrado — todas as frases serão 'narrator'.")


# ── API routes ──────────────────────────────────────────────────────────────

@app.get("/api/config")
def app_config():
    """Frontend uses this to choose speed slider steps (ElevenLabs vs Azure range)."""
    eff = effective_tts_provider(TTS_PROVIDER)
    return {
        "tts_provider": TTS_PROVIDER,
        "effective_provider": eff,
        "speed_step_mode": "elevenlabs" if eff == "elevenlabs" else "azure",
        "elevenlabs_speed_min": 0.7,
        "elevenlabs_speed_max": 1.2,
        "fallback_to_azure": TTS_FALLBACK_TO_AZURE,
    }


@app.get("/api/chapters")
def list_chapters():
    return [
        {
            "index": ch.index,
            "title": ch.title,
            "page_start": ch.page_start,
            "page_end": ch.page_end,
            "char_count": ch.char_count,
        }
        for ch in chapters
    ]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving paragraph boundaries."""
    sentences = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # Split on sentence-ending punctuation followed by whitespace
        parts = re.split(r"(?<=[.!?])\s+", para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


@app.get("/api/chapters/{index}/text")
def chapter_text(index: int):
    if index < 0 or index >= len(chapters):
        raise HTTPException(404, "Capítulo não encontrado")
    ch = chapters[index]
    sentences = _split_sentences(ch.body)

    # Attach speaker tags if available
    ch_tags = speaker_tags.get(str(ch.index), {}).get("speakers", {})
    speakers = [ch_tags.get(str(i), "narrator") for i in range(len(sentences))]

    return {
        "index": ch.index,
        "title": ch.title,
        "body": ch.body,
        "sentences": sentences,
        "speakers": speakers,
        "page_start": ch.page_start,
        "page_end": ch.page_end,
        "total_chapters": len(chapters),
    }


class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    chapter_title: str | None = None
    speaker: str = "narrator"


@app.post("/api/tts")
def tts_endpoint(req: TTSRequest):
    if TTS_PROVIDER == "elevenlabs" and not ELEVENLABS_API_KEY:
        raise HTTPException(500, "ELEVENLABS_API_KEY não configurada no .env")
    if TTS_PROVIDER == "azure" and (not AZURE_KEY or not AZURE_REGION):
        raise HTTPException(500, "Credenciais Azure não configuradas no .env")
    if (
        TTS_PROVIDER == "elevenlabs"
        and TTS_FALLBACK_TO_AZURE
        and (not AZURE_KEY or not AZURE_REGION)
    ):
        raise HTTPException(
            500,
            "Para fallback Azure após ElevenLabs, configure AZURE_SPEECH_KEY e AZURE_SPEECH_REGION no .env",
        )

    # Pick ElevenLabs voice based on speaker
    voice_id = ELEVENLABS_VOICE_ID
    if req.speaker == "et" and ELEVENLABS_ET_VOICE_ID:
        voice_id = ELEVENLABS_ET_VOICE_ID
    elif req.speaker == "baruck" and ELEVENLABS_BARUCK_VOICE_ID:
        voice_id = ELEVENLABS_BARUCK_VOICE_ID

    try:
        if TTS_PROVIDER == "elevenlabs" and TTS_FALLBACK_TO_AZURE:
            audio, used = synthesize_with_fallback(
                req.text,
                preferred_provider="elevenlabs",
                fallback_to_azure=True,
                speed=req.speed,
                chapter_title=req.chapter_title,
                azure_key=AZURE_KEY,
                azure_region=AZURE_REGION,
                elevenlabs_api_key=ELEVENLABS_API_KEY,
                elevenlabs_voice_id=voice_id,
            )
        else:
            audio = synthesize_to_bytes(
                text=req.text,
                provider=TTS_PROVIDER,
                speed=req.speed,
                chapter_title=req.chapter_title,
                azure_key=AZURE_KEY,
                azure_region=AZURE_REGION,
                elevenlabs_api_key=ELEVENLABS_API_KEY,
                elevenlabs_voice_id=voice_id,
            )
            used = effective_tts_provider(TTS_PROVIDER)
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={"X-Effective-TTS-Provider": used},
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))


class BookmarkRequest(BaseModel):
    chapter_index: int
    chapter_title: str
    sentence_index: int
    sentence_text: str


@app.post("/api/bookmarks")
def save_bookmark(req: BookmarkRequest):
    bm = add_bookmark(req.chapter_index, req.chapter_title, req.sentence_index, req.sentence_text)
    return bm


@app.get("/api/bookmarks")
def list_bookmarks():
    return get_bookmarks()


# ── Serve static files (must be last) ──────────────────────────────────────

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
