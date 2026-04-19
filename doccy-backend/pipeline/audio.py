"""
Audio capture and VAD.

VAD: Silero — reliable speech boundary detection.
Note: cactus_vad is NOT used — it segfaults on Gemma 4 models
because it only supports Whisper-based architectures.
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave
import time
import numpy as np
import sounddevice as sd
import torch

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SAMPLE_RATE             = 16000
CHANNELS                = 1
FRAME_SAMPLES           = 512       # sounddevice blocksize — 32ms @ 16kHz

MAX_SEGMENT_SEC         = 8.0
MIN_SEGMENT_SEC         = 0.30
ENCODER_FRAME           = 640       # Gemma 4 audio encoder: 40ms @ 16kHz

VAD_THRESHOLD           = 0.25
REQUIRED_SILENCE_FRAMES = 5         # Silero silence counter

# ── Silero VAD — loaded at import so capture starts immediately ───────────────

_silero_model = None
_VADIterator  = None


def _load_silero():
    global _silero_model, _VADIterator
    if _silero_model is not None:
        return
    logger.info("[VAD] Loading Silero model...")
    model, utils = torch.hub.load(
        "snakers4/silero-vad", "silero_vad",
        force_reload=False, onnx=False,
    )
    _silero_model = model
    _VADIterator  = utils[3]
    logger.info("[VAD] Silero ready.")


_load_silero()


# ── Audio utilities ───────────────────────────────────────────────────────────

def audio_to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """float32 numpy → 16-bit PCM WAV bytes."""
    pcm16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    buf   = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _align_to_encoder_frame(audio: np.ndarray) -> np.ndarray:
    """Pad to nearest 640-sample (40ms) boundary — required by Gemma 4 encoder."""
    rem = len(audio) % ENCODER_FRAME
    if rem:
        audio = np.concatenate([audio, np.zeros(ENCODER_FRAME - rem, dtype=np.float32)])
    return audio


# ── Main stream class ─────────────────────────────────────────────────────────

class AudioStream:
    """
    Sounddevice InputStream + Silero VAD + optional speculative KV prefill.

    Call start(loop) to open the mic and begin Silero VAD.
    Call enable_speculative_prefill(...) once the Cactus model is loaded to
    activate cactus_prefill bursts during active speech.
    """

    def __init__(self):
        self._frame_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=1000)
        self._chunk_queue: asyncio.Queue[tuple[float, np.ndarray]] = asyncio.Queue()
        self._stream:   sd.InputStream | None = None
        self._vad_task: asyncio.Task   | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        def _callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"sounddevice: {status}")
            frame = indata[:, 0].copy()
            def _put(f=frame):
                try:
                    self._frame_queue.put_nowait(f)
                except asyncio.QueueFull:
                    pass   # drop frame — VAD is behind, not catastrophic
            loop.call_soon_threadsafe(_put)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=FRAME_SAMPLES,
            callback=_callback,
        )
        self._stream.start()
        self._vad_task = loop.create_task(self._silero_vad_worker(), name="silero-vad")
        logger.info("[VAD] Silero VAD active — mic open.")

    async def stop(self) -> None:
        # Stop sounddevice FIRST so the callback stops firing before VAD is cancelled.
        # Reversing this order causes QueueFull errors during shutdown.
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"Error closing stream: {e}")
            self._stream = None
        if self._vad_task and not self._vad_task.done():
            self._vad_task.cancel()
            try:
                await self._vad_task
            except asyncio.CancelledError:
                pass
        logger.info("Audio stream stopped.")

    # ── Silero VAD worker with speculative prefill ────────────────────────────

    async def _silero_vad_worker(self) -> None:
        loop = asyncio.get_running_loop()

        logger.info("[VAD] worker started — listening for speech")

        vad_iter = _VADIterator(
            _silero_model,
            threshold=VAD_THRESHOLD,
            sampling_rate=SAMPLE_RATE,
        )
        buffer: list[np.ndarray] = []
        silence_count = 0
        in_speech     = False
        speech_started_at: float | None = None
        MAX_FRAMES    = int(MAX_SEGMENT_SEC * SAMPLE_RATE / FRAME_SAMPLES)

        try:
            while True:
                frame = await self._frame_queue.get()

                # ── Silero VAD ────────────────────────────────────────────────
                peak = float(np.max(np.abs(frame)))
                if peak > 1.0:
                    frame = frame / peak

                vad_out = vad_iter(frame, return_seconds=True)
                if isinstance(vad_out, dict):
                    if "start" in vad_out:
                        in_speech        = True
                        silence_count    = 0
                        speech_started_at = time.perf_counter()
                        logger.info("[VAD] speech START detected")
                    if "end" in vad_out:
                        in_speech = False
                        dur = (time.perf_counter() - speech_started_at) if speech_started_at else 0
                        logger.info(f"[VAD] speech END detected — duration {dur*1000:.0f}ms")

                if in_speech:
                    buffer.append(frame)
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count <= REQUIRED_SILENCE_FRAMES:
                        buffer.append(frame)

                seal_silence = (
                    silence_count >= REQUIRED_SILENCE_FRAMES
                    and len(buffer) * FRAME_SAMPLES / SAMPLE_RATE >= MIN_SEGMENT_SEC
                )
                seal_max = len(buffer) >= MAX_FRAMES

                # ── Seal chunk ────────────────────────────────────────────────
                if seal_silence or seal_max:
                    if buffer:
                        chunk     = _align_to_encoder_frame(np.concatenate(buffer))
                        sealed_at = time.perf_counter()
                        await self._chunk_queue.put((sealed_at, chunk))
                        logger.info(
                            f"[VAD] chunk SEALED {len(chunk)/SAMPLE_RATE:.2f}s "
                            f"reason={'silence' if seal_silence else 'max_len'}  "
                            f"pending_in_queue={self._chunk_queue.qsize()}"
                        )
                    buffer            = []
                    silence_count     = 0
                    in_speech         = False
                    speech_started_at = None
                    vad_iter.reset_states()

        except asyncio.CancelledError:
            logger.info("[VAD] worker stopped.")

    async def get_chunk(self) -> tuple[float, np.ndarray]:
        return await self._chunk_queue.get()


# Module-level singleton
audio_stream = AudioStream()
