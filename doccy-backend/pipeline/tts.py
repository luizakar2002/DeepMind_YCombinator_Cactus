
#!/usr/bin/env python3
"""
Low-latency OpenAI Text-to-Speech with streaming playback.
Uses sounddevice — no C++ compiler required, installs cleanly on Windows.

Requirements:
    pip install openai sounddevice numpy

Set your key:
    export OPENAI_API_KEY="sk-..."   (Windows: set OPENAI_API_KEY=sk-...)
"""

import os
import sys
import numpy as np
import sounddevice as sd
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
MODEL      = "tts-1"    # tts-1 = lowest latency | tts-1-hd = higher quality
VOICE      = "alloy"    # alloy | echo | fable | onyx | nova | shimmer
SPEED      = 1.0        # 0.25 – 4.0
FORMAT_OUT = "pcm"      # raw 16-bit PCM → no decode overhead

# PCM output spec from OpenAI: 24 kHz, mono, signed 16-bit little-endian
SAMPLE_RATE = 24_000
CHANNELS    = 1
DTYPE       = np.int16
CHUNK_SIZE  = 4096      # bytes per iteration — smaller = lower first-sound latency
# ─────────────────────────────────────────────────────────────────────────────


def stream_tts(text: str) -> None:
    client = OpenAI()  # reads OPENAI_API_KEY from environment

    # RawOutputStream lets us push raw PCM bytes as they arrive
    stream = sd.RawOutputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
    )

    print(f"[TTS] Streaming → voice={VOICE}  model={MODEL}")
    stream.start()
    try:
        with client.audio.speech.with_streaming_response.create(
            model=MODEL,
            voice=VOICE,
            input=text,
            speed=SPEED,
            response_format=FORMAT_OUT,
        ) as response:
            for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                stream.write(chunk)   # play each chunk immediately
    finally:
        stream.stop()
        stream.close()

    print("[TTS] Done.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = (
            "Hello! This is a low-latency streaming text-to-speech demo "
            "using the OpenAI API. Audio plays as the chunks arrive."
        )

    stream_tts(text)