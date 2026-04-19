"""
Standalone pipeline debug — no server, no WebSocket.
Run from doccy-backend/:
    python debug_pipeline.py

Speak into the mic. Each detected utterance prints:
  [CHUNK]   → audio captured, N samples
  [GEMMA]   → raw model output
  [ENTITIES]→ parsed JSON
"""

import asyncio
import json
import sys
from pathlib import Path

# Same path fix as inference.py
sys.path.insert(0, str(Path(__file__).parent.parent / "cactus" / "python"))

from pipeline.audio import audio_chunks, audio_to_wav_bytes
from pipeline.inference import _run_extraction, _build_system_prompt
from pipeline.ehr import load_patient

PATIENT = load_patient("anna_hakobyan")
SYSTEM_PROMPT = _build_system_prompt(PATIENT)

print("=" * 60)
print("  DOCCY — Pipeline Debug")
print(f"  Patient: {PATIENT.name if PATIENT else 'none'}")
print("  Speak into the mic. Ctrl+C to stop.")
print("=" * 60)


async def main():
    chunk_num = 0
    async for chunk in audio_chunks():
        chunk_num += 1
        duration = len(chunk) / 16000
        print(f"\n[CHUNK {chunk_num}] {len(chunk)} samples / {duration:.2f}s")

        print("[GEMMA ] running inference...")
        try:
            transcript, entities = _run_extraction(chunk, SYSTEM_PROMPT)
            print(f"[GEMMA ] {transcript[:120]}")
            print(f"[ENTITIES] {json.dumps(entities, indent=2)}")
        except Exception as e:
            print(f"[ERROR ] {e}")


asyncio.run(main())
