"""Analyze book text with GPT-4.1-mini to identify three speakers:
Ilana (narrator/author), Baruck (spiritual master), and the ETs.

Reads the .docx, sends each chapter to the LLM, and produces a JSON file
mapping (chapter_index, sentence_index) → speaker ("ilana" | "baruck" | "et").

Usage:
    python3 tag_speakers.py                  # uses .env for config
    python3 tag_speakers.py --chapter 5      # process only chapter 5
    python3 tag_speakers.py --dry-run        # print prompt for chapter 0 without calling API
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

from parser import parse_docx

load_dotenv(Path(__file__).parent / ".env")

DOCX_PATH = os.getenv("DOCX_PATH", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Azure OpenAI config (used when AZURE_OPENAI_ENDPOINT is set)
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")

MODEL = "gpt-4.1-mini"
OUTPUT_FILE = Path(__file__).parent / "speaker_tags.json"


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


SYSTEM_PROMPT = """\
Você é um especialista em análise literária de textos em português brasileiro.

O livro que você vai analisar é um relato espiritual escrito por Ilana. Ele descreve \
seus encontros meditativos com seres extraterrestres (ETs), guiados por seu Mestre \
Espiritual, Baruck. O livro NÃO usa aspas, travessão nem qualquer marcação para \
diferenciar quem está falando. Você precisa inferir pelo conteúdo, tom e contexto.

Existem TRÊS falantes:

1. **ilana** — A autora e narradora humana.
   - Fala em 1ª pessoa do singular: "eu", "minha", "me", "senti", "percebi", "compreendi".
   - Descreve suas experiências de meditação: "todas as vezes que meditava", "adormeci \
durante minha concentração", "fui guiada ao plano espiritual".
   - Expressa dúvidas, medos e emoções: "tive um período de dúvidas", "sempre me emociona".
   - Narra cenários, descreve o templo, a montanha, a viagem astral.
   - Refere-se a "meu Mestre" ou "Baruck" como seu guia.
   - Faz introduções e transições entre falas dos outros personagens.
   - Inclui observações pessoais: "Imagine a minha enorme dificuldade…"

2. **baruck** — O Mestre Espiritual de Ilana (um espírito elevado, não um ET).
   - Aparece PRINCIPALMENTE no Capítulo 1 ("Introdução de Baruck") e em \
passagens introdutórias ou de transição ao longo do livro.
   - Usa "nós" em contexto espiritual (referindo-se a espíritos guias, não ao planeta dos ETs).
   - Tom paternal, orientador e esperançoso: "Queremos oferecer esperança", \
"Sabemos que uma força maior nos guia", "Essa felicidade está ao nosso alcance".
   - Fala sobre a missão do livro: mostrar que Planetas Felizes existem para dar ânimo.
   - Usa linguagem simples e acessível intencionalmente: "Usamos uma linguagem simples \
porque não existem palavras perfeitas".
   - NÃO descreve o planeta dos ETs em detalhe; NÃO chama Ilana de "irmã".

3. **et** — Os seres extraterrestres (ETs / irmãos estelares).
   - Chamam Ilana de "irmã" ou "querida irmã".
   - Usam "nós"/"nosso" referindo-se a SEU PLANETA e sua civilização: \
"nosso planeta", "em nosso mundo", "nós, que somos de outro orbe".
   - Usam "vocês"/"seu" referindo-se aos humanos/Terra: "vocês humanos", \
"seu planeta", "seu povo", "o planeta de vocês".
   - Descrevem em detalhe seu planeta: geologia, atmosfera, água, vegetação, \
animais luminosos, construções, costumes, tecnologia telepática.
   - Falam de temas cósmicos com autoridade de quem VIVE em outro mundo: \
fendas dimensionais, comutação de pensamentos, reencarnação interplanetária.
   - Fazem comparações diretas entre a vida deles e a da Terra.
   - Tom filosófico mas também carinhoso e paciente.
   - Às vezes há marcadores no texto como "(ET)" ou "(Um Diálogo entre Mundos - ET)".

REGRA FUNDAMENTAL — MENCIONAR NÃO É FALAR:
Ilana frequentemente MENCIONA Baruck e os ETs no texto sem que eles estejam FALANDO. \
A pergunta-chave é: "Quem é o DONO da voz nesta frase?" — quem está se expressando, \
não quem é mencionado.

EXEMPLOS DE ERROS COMUNS (NÃO COMETA ESTES):
❌ "Meu Mestre Espiritual instigou-me a dedicar-me às práticas de meditação." \
→ NÃO é Baruck falando. É Ilana narrando o que ele fez. A palavra "meu" e "me" \
indicam que Ilana é a voz. → "ilana"
❌ "Estes seres desejam que eu os descreva: como vivem, como evoluíram." \
→ NÃO é os ETs falando. É Ilana descrevendo o desejo deles. "eu os descreva" = voz de Ilana. → "ilana"
❌ "Eles me disseram que a insegurança faz parte dessa jornada." \
→ NÃO é os ETs falando. É Ilana relatando indiretamente o que eles disseram. → "ilana"
❌ "Baruck, meu Mestre Espiritual, foi quem me introduziu no encontro com esses seres." \
→ NÃO é Baruck. É Ilana falando sobre ele. → "ilana"

EXEMPLOS CORRETOS:
✅ "Irmã, sua colaboração em nossas escritas é essencial." → ET falando (chama "irmã", usa "nossas"). → "et"
✅ "Queremos, com palavras simples, falar da existência de um Planeta Feliz." → Baruck falando \
(Cap. 1, voz ativa sem "eu" de Ilana, tom de guia espiritual). → "baruck"
✅ "Iniciar minha jornada de meditação foi um desafio." → Ilana narrando ("minha jornada"). → "ilana"

OUTRAS REGRAS:
- Quando houver marcadores como "(ET)" ou "(- ET)" na frase, marque como "et". \
Títulos de seção como "(A Visão do Mal)" sem indicação de falante → "ilana".
- Todo o Prefácio é narrado por Ilana. Baruck NÃO fala no Prefácio.
- Baruck fala quase exclusivamente no Capítulo 1 e em raras passagens introdutórias.
- Frases com "eu", "me", "minha", "meu", "senti", "percebi" quase sempre são Ilana, \
MESMO que mencionem ETs ou Baruck no conteúdo.
- Fala indireta ("Eles me disseram que...", "O ET nos recebeu e disse...") = Ilana narrando.
- Fala direta implícita (sem aspas, mas o personagem fala por si) = o personagem.
- Na dúvida, marque como "ilana"."""


def build_user_prompt(chapter_title: str, sentences: list[str]) -> str:
    lines = []
    lines.append(f"## {chapter_title}\n")
    lines.append("Abaixo estão as frases numeradas deste capítulo. "
                  "Para cada frase, responda APENAS com o JSON pedido.\n")
    for i, s in enumerate(sentences):
        lines.append(f"[{i}] {s}")

    lines.append("\n---\n")
    lines.append('Responda com um JSON no formato: {"sentences": [{"idx": 0, "speaker": "ilana"}, {"idx": 1, "speaker": "et"}, {"idx": 2, "speaker": "baruck"}, ...]}')
    lines.append('Os valores possíveis para "speaker" são: "ilana", "baruck", "et".')
    lines.append("Inclua TODAS as frases (de 0 a " + str(len(sentences) - 1) + "). "
                 "Retorne SOMENTE o JSON, sem markdown, sem explicação.")
    return "\n".join(lines)


def _get_client():
    if AZURE_OPENAI_ENDPOINT:
        return AzureOpenAI(
            api_key=OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version=AZURE_OPENAI_API_VERSION,
        ), AZURE_OPENAI_DEPLOYMENT
    return OpenAI(api_key=OPENAI_API_KEY), MODEL


def call_llm(chapter_title: str, sentences: list[str]) -> list[dict]:
    client, model = _get_client()

    user_prompt = build_user_prompt(chapter_title, sentences)

    resp = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw = resp.choices[0].message.content.strip()
    parsed = json.loads(raw)

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # Look for a list value under any key
        for key in ("sentences", "results", "data", "tags"):
            if key in parsed and isinstance(parsed[key], list):
                return parsed[key]
        for v in parsed.values():
            if isinstance(v, list):
                return v
        # Single object with idx/speaker — wrap in list
        if "idx" in parsed and "speaker" in parsed:
            return [parsed]
    raise ValueError(f"Unexpected LLM response format: {raw[:300]}")


def process_chapter(chapter, existing_tags: dict) -> dict:
    sentences = _split_sentences(chapter.body)
    if not sentences:
        return existing_tags

    print(f"  → {len(sentences)} frases, chamando {MODEL}...", end=" ", flush=True)
    t0 = time.time()
    tags = call_llm(chapter.title, sentences)
    elapsed = time.time() - t0
    print(f"OK ({elapsed:.1f}s)")

    counts = {"ilana": 0, "baruck": 0, "et": 0}
    for t in tags:
        s = t.get("speaker", "ilana")
        counts[s] = counts.get(s, 0) + 1
    print(f"    Ilana: {counts['ilana']} | Baruck: {counts['baruck']} | ET: {counts['et']}")

    # Build mapping: sentence_index → speaker
    chapter_key = str(chapter.index)
    mapping = {}
    for t in tags:
        idx = t.get("idx", t.get("index"))
        speaker = t.get("speaker", "narrator")
        if idx is not None:
            mapping[str(idx)] = speaker

    existing_tags[chapter_key] = {
        "title": chapter.title,
        "sentence_count": len(sentences),
        "speakers": mapping,
    }
    return existing_tags


def main():
    parser = argparse.ArgumentParser(description="Tag speakers (Ilana / Baruck / ET) in book chapters")
    parser.add_argument("--chapter", type=int, default=None,
                        help="Process only this chapter index")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt for chapter 0 without calling the API")
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        print("ERRO: OPENAI_API_KEY não configurada no .env")
        print("Adicione: OPENAI_API_KEY=sk-...")
        sys.exit(1)

    if not DOCX_PATH or not Path(DOCX_PATH).exists():
        print(f"ERRO: Arquivo .docx não encontrado: '{DOCX_PATH}'")
        sys.exit(1)

    print(f"Carregando livro: {DOCX_PATH}")
    chapters = parse_docx(DOCX_PATH)
    print(f"Total: {len(chapters)} capítulos\n")

    if args.dry_run:
        ch = chapters[args.chapter or 0]
        sentences = _split_sentences(ch.body)
        prompt = build_user_prompt(ch.title, sentences)
        print("=== SYSTEM PROMPT ===")
        print(SYSTEM_PROMPT)
        print("\n=== USER PROMPT ===")
        print(prompt)
        print(f"\n({len(sentences)} frases, ~{len(prompt)} chars)")
        return

    # Load existing tags (for incremental runs)
    existing_tags = {}
    if OUTPUT_FILE.exists():
        existing_tags = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))

    to_process = chapters
    if args.chapter is not None:
        to_process = [ch for ch in chapters if ch.index == args.chapter]
        if not to_process:
            print(f"Capítulo {args.chapter} não encontrado.")
            sys.exit(1)

    for ch in to_process:
        print(f"[{ch.index}] {ch.title}")
        try:
            existing_tags = process_chapter(ch, existing_tags)
        except Exception as e:
            print(f"  ERRO: {e}")
            continue

        # Save after each chapter (resilient to interruptions)
        OUTPUT_FILE.write_text(
            json.dumps(existing_tags, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"\nResultado salvo em: {OUTPUT_FILE}")

    # Summary
    totals = {"ilana": 0, "baruck": 0, "et": 0}
    total_all = 0
    for ch_data in existing_tags.values():
        speakers = ch_data.get("speakers", {})
        total_all += len(speakers)
        for s in speakers.values():
            totals[s] = totals.get(s, 0) + 1
    print(f"Total: {total_all} frases analisadas")
    print(f"  Ilana: {totals['ilana']} | Baruck: {totals['baruck']} | ET: {totals['et']}")


if __name__ == "__main__":
    main()
