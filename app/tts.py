"""TTS integration with Azure and ElevenLabs backends, plus file-based caching."""

import hashlib
import re
from pathlib import Path

import httpx
import azure.cognitiveservices.speech as speechsdk

CACHE_DIR = Path(__file__).parent / "audio_cache"
CACHE_DIR.mkdir(exist_ok=True)

_UNITS = [
    "", "Um", "Dois", "Três", "Quatro", "Cinco",
    "Seis", "Sete", "Oito", "Nove", "Dez",
    "Onze", "Doze", "Treze", "Quatorze", "Quinze",
    "Dezesseis", "Dezessete", "Dezoito", "Dezenove", "Vinte",
]
_TENS = [
    "", "", "Vinte", "Trinta", "Quarenta", "Cinquenta",
    "Sessenta", "Setenta", "Oitenta", "Noventa", "Cem",
]

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"

# ElevenLabs API accepts ~0.25–4.0; we keep a narrow band so the user can go “a little” faster.
ELEVENLABS_SPEED_MIN = 0.7
ELEVENLABS_SPEED_MAX = 1.2


def clamp_elevenlabs_speed(speed: float) -> float:
    s = float(speed)
    return max(ELEVENLABS_SPEED_MIN, min(ELEVENLABS_SPEED_MAX, s))

# Set to True after ElevenLabs returns quota / credit errors; then Azure is used.
_elevenlabs_exhausted: bool = False


def is_elevenlabs_exhausted() -> bool:
    return _elevenlabs_exhausted


def reset_elevenlabs_exhausted() -> None:
    """For tests or manual recovery; restart server also resets this."""
    global _elevenlabs_exhausted
    _elevenlabs_exhausted = False


def effective_tts_provider(preferred: str) -> str:
    """Which engine is actually used for new synthesis (after fallback)."""
    if preferred == "elevenlabs" and not _elevenlabs_exhausted:
        return "elevenlabs"
    return "azure"


def _is_elevenlabs_quota_error(err: RuntimeError | Exception) -> bool:
    """True only for quota / billing / rate-limit — not for invalid API key (401)."""
    msg = str(err).lower()
    if "quota_exceeded" in msg:
        return True
    if "quota" in msg and "exceed" in msg:
        return True
    if "not enough" in msg and "credit" in msg:
        return True
    if "insufficient" in msg and ("credit" in msg or "quota" in msg):
        return True
    if "requires" in msg and "credit" in msg:
        return True
    # Payment / plan limits (body often includes these strings)
    if "elevenlabs api error 402" in msg:
        return True
    if "elevenlabs api error 429" in msg:
        return True
    return False


# ── Shared helpers ───────────────────────────────────────────────────────────

def _number_to_portuguese(n: int) -> str:
    if n <= 0:
        return str(n)
    if n <= 20:
        return _UNITS[n]
    if n < 100:
        tens, units = divmod(n, 10)
        if units == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} e {_UNITS[units]}"
    if n == 100:
        return "Cem"
    return str(n)


def _chapter_title_spoken(title: str) -> str:
    """Convert 'Capítulo 12' to 'Capítulo Doze' for natural speech."""
    match = re.search(r"(\d+)", title)
    if match:
        num = int(match.group(1))
        word = _number_to_portuguese(num)
        return title[: match.start()] + word + title[match.end() :]
    return title


def _cache_key(
    provider: str, text: str, voice: str, speed: float, chapter_title: str | None
) -> str:
    raw = f"{provider}|{text}|{voice}|{speed}|{chapter_title or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ── Azure backend ────────────────────────────────────────────────────────────

def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _build_ssml(
    text: str,
    voice: str,
    speed: float,
    chapter_title: str | None = None,
) -> str:
    rate_pct = f"{speed * 100:.0f}%"
    body_parts: list[str] = []

    if chapter_title:
        spoken_title = _chapter_title_spoken(chapter_title)
        body_parts.append(f"    {_escape_xml(spoken_title)}")
        body_parts.append('    <break time="1000ms"/>')

    paragraphs = text.split("\n\n")
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for j, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            body_parts.append(f"    {_escape_xml(sentence)}")
            if j < len(sentences) - 1:
                body_parts.append('    <break time="300ms"/>')
        if i < len(paragraphs) - 1:
            body_parts.append('    <break time="600ms"/>')

    inner = "\n".join(body_parts)
    return f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="pt-BR">
  <voice name="{voice}">
    <prosody rate="{rate_pct}">
{inner}
    </prosody>
  </voice>
</speak>"""


def _synthesize_azure(
    text: str,
    key: str,
    region: str,
    voice: str,
    speed: float,
    chapter_title: str | None,
) -> bytes:
    speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )
    synthesizer = speechsdk.SpeechSynthesizer(
        speech_config=speech_config, audio_config=None
    )
    ssml = _build_ssml(text, voice=voice, speed=speed, chapter_title=chapter_title)
    result = synthesizer.speak_ssml_async(ssml).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return result.audio_data
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation = result.cancellation_details
        raise RuntimeError(
            f"Azure TTS canceled: {cancellation.reason}. Error: {cancellation.error_details}"
        )
    else:
        raise RuntimeError(f"Azure TTS failed: {result.reason}")


# ── ElevenLabs backend ──────────────────────────────────────────────────────

def _build_text_elevenlabs(
    text: str,
    chapter_title: str | None = None,
) -> str:
    parts: list[str] = []
    if chapter_title:
        parts.append(_chapter_title_spoken(chapter_title) + ".")
    parts.append(text)
    return "\n\n".join(parts)


def _synthesize_elevenlabs(
    text: str,
    api_key: str,
    voice_id: str,
    speed: float,
    chapter_title: str | None,
) -> bytes:
    final_text = _build_text_elevenlabs(text, chapter_title=chapter_title)

    url = f"{ELEVENLABS_API_BASE}/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": final_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.50,
            "similarity_boost": 0.75,
            "speed": speed,
        },
    }

    print(f"ElevenLabs TTS: speed={speed}", flush=True)
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        detail = resp.text[:300]
        raise RuntimeError(f"ElevenLabs API error {resp.status_code}: {detail}")

    return resp.content


# ── Unified entry point with caching ────────────────────────────────────────

def synthesize_to_bytes(
    text: str,
    provider: str = "azure",
    speed: float = 1.0,
    chapter_title: str | None = None,
    # Azure params
    azure_key: str = "",
    azure_region: str = "",
    azure_voice: str = "pt-BR-FranciscaNeural",
    # ElevenLabs params
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "",
) -> bytes:
    """Synthesize text to MP3 bytes using the chosen provider, with caching."""
    if provider == "elevenlabs":
        speed = clamp_elevenlabs_speed(speed)

    voice = azure_voice if provider == "azure" else elevenlabs_voice_id
    key = _cache_key(provider, text, voice, speed, chapter_title)
    cached_path = CACHE_DIR / f"{key}.mp3"

    if cached_path.exists():
        return cached_path.read_bytes()

    if provider == "elevenlabs":
        audio = _synthesize_elevenlabs(
            text, api_key=elevenlabs_api_key, voice_id=elevenlabs_voice_id,
            speed=speed, chapter_title=chapter_title,
        )
    else:
        audio = _synthesize_azure(
            text, key=azure_key, region=azure_region, voice=azure_voice,
            speed=speed, chapter_title=chapter_title,
        )

    cached_path.write_bytes(audio)
    return audio


def synthesize_with_fallback(
    text: str,
    *,
    preferred_provider: str,
    fallback_to_azure: bool,
    speed: float,
    chapter_title: str | None,
    azure_key: str,
    azure_region: str,
    azure_voice: str = "pt-BR-FranciscaNeural",
    elevenlabs_api_key: str,
    elevenlabs_voice_id: str,
) -> tuple[bytes, str]:
    """Try ElevenLabs first; on quota errors switch to Azure for this and later requests.

    Returns (mp3_bytes, engine_used) where engine_used is ``elevenlabs`` or ``azure``.
    """
    global _elevenlabs_exhausted

    if preferred_provider == "azure":
        return (
            synthesize_to_bytes(
                text=text,
                provider="azure",
                speed=speed,
                chapter_title=chapter_title,
                azure_key=azure_key,
                azure_region=azure_region,
                azure_voice=azure_voice,
                elevenlabs_api_key=elevenlabs_api_key,
                elevenlabs_voice_id=elevenlabs_voice_id,
            ),
            "azure",
        )

    if preferred_provider != "elevenlabs":
        raise ValueError(f"Unknown provider: {preferred_provider}")

    if _elevenlabs_exhausted:
        return (
            synthesize_to_bytes(
                text=text,
                provider="azure",
                speed=speed,
                chapter_title=chapter_title,
                azure_key=azure_key,
                azure_region=azure_region,
                azure_voice=azure_voice,
                elevenlabs_api_key=elevenlabs_api_key,
                elevenlabs_voice_id=elevenlabs_voice_id,
            ),
            "azure",
        )

    try:
        audio = synthesize_to_bytes(
            text=text,
            provider="elevenlabs",
            speed=speed,
            chapter_title=chapter_title,
            azure_key=azure_key,
            azure_region=azure_region,
            azure_voice=azure_voice,
            elevenlabs_api_key=elevenlabs_api_key,
            elevenlabs_voice_id=elevenlabs_voice_id,
        )
        return (audio, "elevenlabs")
    except RuntimeError as e:
        if (
            fallback_to_azure
            and azure_key
            and azure_region
            and _is_elevenlabs_quota_error(e)
        ):
            _elevenlabs_exhausted = True
            print(
                "TTS: cota ElevenLabs esgotada ou erro de quota; "
                "usando Azure daqui em diante.",
                flush=True,
            )
            audio = synthesize_to_bytes(
                text=text,
                provider="azure",
                speed=speed,
                chapter_title=chapter_title,
                azure_key=azure_key,
                azure_region=azure_region,
                azure_voice=azure_voice,
                elevenlabs_api_key=elevenlabs_api_key,
                elevenlabs_voice_id=elevenlabs_voice_id,
            )
            return (audio, "azure")
        raise
