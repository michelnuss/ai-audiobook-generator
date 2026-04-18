# 📖 AI Audiobook Generator

**Transform any book into a fully voiced, multi-character audiobook using LLMs and ElevenLabs.**

> Built to convert my grandmother Ilana's written book into a professional-quality audiobook, with a unique human voice for every character.

---

## How It Works

The pipeline runs in four stages:

### 1. Character Extraction (LLM)
An LLM reads the full text and identifies every distinct character, extracting their name, role, personality traits, and speaking style. The model builds a character registry that maps each line of dialogue to its speaker, handling edge cases like unnamed narrators, group dialogue, and characters referred to by multiple names.

### 2. Voice Assignment (ElevenLabs)
Each character in the registry is matched to a distinct human voice from ElevenLabs' voice library. Voices are selected to reflect the character's described age, gender, tone, and personality, so that a grandmother sounds different from a child, and a stern authority figure sounds different from a warm friend.

### 3. Multi-Voice Synthesis
The system walks through the book chapter by chapter, routing each passage to the correct voice: narration goes to the narrator voice, and every line of dialogue is synthesized with the assigned character's voice. Transitions between speakers are handled seamlessly, producing a natural listening experience.

### 4. Export
Chapters are stitched together and exported as a downloadable audiobook, ready for any player.

---

## Tech Stack

| Layer | Tools |
|---|---|
| Character analysis | GPT-4o (structured extraction, dialogue attribution) |
| Text-to-speech | ElevenLabs API (multi-voice, human-quality synthesis) |
| Audio processing | Python (pydub, file stitching, chapter segmentation) |
| Orchestration | Python end-to-end pipeline |

---

## Why I Built This

My grandmother Ilana wrote a book about her life. I wanted her to be able to hear it read back to her with every character brought to life in a distinct voice, not a flat single-narrator TTS output. This project started as a personal gift and turned into a general-purpose pipeline that can convert any book into a multi-character audiobook.

---

## Usage

```bash
# Clone the repo
git clone https://github.com/michelnuss/ai-audiobook-generator.git
cd ai-audiobook-generator

# Install dependencies
pip install -r requirements.txt

# Set API keys
export OPENAI_API_KEY=your_key
export ELEVENLABS_API_KEY=your_key

# Run the pipeline
python main.py --input book.txt --output audiobook/
```
