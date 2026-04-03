"""Pre-generate all TTS audio for the book so the app runs without API calls."""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from parser import parse_docx
from tts import reset_elevenlabs_exhausted, synthesize_to_bytes, synthesize_with_fallback

CHUNK_SIZE = 5


def _split_sentences(text: str) -> list[str]:
    sentences = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        parts = re.split(r"(?<=[.!?])\s+", para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def _build_chunks(sentences: list[str]) -> list[dict]:
    chunks = []
    for i in range(0, len(sentences), CHUNK_SIZE):
        chunks.append({
            "start_idx": i,
            "sentences": sentences[i : i + CHUNK_SIZE],
        })
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Pre-generate audiobook TTS cache")
    parser.add_argument(
        "--speed", type=float, default=0.25,
        help="Playback speed to pre-generate (default: 0.25)",
    )
    parser.add_argument(
        "--provider", type=str, default=None,
        help="TTS provider: azure or elevenlabs (default: from .env)",
    )
    args = parser.parse_args()

    provider = (args.provider or os.getenv("TTS_PROVIDER", "azure")).lower()
    fallback = os.getenv("TTS_FALLBACK_TO_AZURE", "true").lower() in ("1", "true", "yes")
    azure_key = os.getenv("AZURE_SPEECH_KEY", "")
    azure_region = os.getenv("AZURE_SPEECH_REGION", "")
    elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id = os.getenv("ELEVENLABS_VOICE_ID", "GIuLCSVfgJaUuh7hYOY8")
    docx_path = os.getenv("DOCX_PATH", "")

    reset_elevenlabs_exhausted()

    if provider == "elevenlabs" and not elevenlabs_api_key:
        print("ERRO: ELEVENLABS_API_KEY não configurada no .env")
        sys.exit(1)
    if provider == "azure" and (not azure_key or not azure_region):
        print("ERRO: Credenciais Azure não configuradas no .env")
        sys.exit(1)
    if provider == "elevenlabs" and fallback and (not azure_key or not azure_region):
        print(
            "ERRO: TTS_FALLBACK_TO_AZURE exige AZURE_SPEECH_KEY e AZURE_SPEECH_REGION no .env"
        )
        sys.exit(1)
    if not docx_path or not Path(docx_path).exists():
        print(f"ERRO: Arquivo .docx não encontrado em '{docx_path}'")
        sys.exit(1)

    chapters = parse_docx(docx_path)
    print(f"Livro carregado: {len(chapters)} capítulos")
    print(f"Provedor: {provider}")
    if provider == "elevenlabs" and fallback:
        print(
            "Modo: ElevenLabs até acabar a cota, depois Azure. "
            "Velocidade ElevenLabs 1.0x; Azure usa --speed."
        )
        print(f"Velocidade Azure (fallback): {args.speed}x\n")
    elif provider == "elevenlabs":
        print("Velocidade: 1.0x (fixo para ElevenLabs; --speed ignorado)\n")
    else:
        print(f"Velocidade: {args.speed}x\n")

    total_chunks = 0
    cached_chunks = 0
    failed_chunks = 0

    for ch in chapters:
        sentences = _split_sentences(ch.body)
        chunks = _build_chunks(sentences)
        print(f"  {ch.title} — {len(chunks)} blocos de áudio")

        for ci, chunk in enumerate(chunks):
            total_chunks += 1
            text = "\n\n".join(chunk["sentences"])
            is_first = chunk["start_idx"] == 0
            chapter_title = ch.title if is_first else None

            try:
                if provider == "elevenlabs" and fallback:
                    synthesize_with_fallback(
                        text,
                        preferred_provider="elevenlabs",
                        fallback_to_azure=True,
                        speed=args.speed,
                        chapter_title=chapter_title,
                        azure_key=azure_key,
                        azure_region=azure_region,
                        elevenlabs_api_key=elevenlabs_api_key,
                        elevenlabs_voice_id=elevenlabs_voice_id,
                    )
                else:
                    synthesize_to_bytes(
                        text=text,
                        provider=provider,
                        speed=args.speed,
                        chapter_title=chapter_title,
                        azure_key=azure_key,
                        azure_region=azure_region,
                        elevenlabs_api_key=elevenlabs_api_key,
                        elevenlabs_voice_id=elevenlabs_voice_id,
                    )
                cached_chunks += 1
                print(f"    bloco {ci + 1}/{len(chunks)} ✓")
            except Exception as e:
                failed_chunks += 1
                print(f"    bloco {ci + 1}/{len(chunks)} ERRO: {e}")

    print(f"\nConcluído: {cached_chunks}/{total_chunks} blocos gerados", end="")
    if failed_chunks:
        print(f" ({failed_chunks} com erro)")
    else:
        print()


if __name__ == "__main__":
    main()
