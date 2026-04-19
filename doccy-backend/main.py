import asyncio
import contextlib
import logging
import json
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import time

from pipeline.audio import audio_stream
from pipeline.ehr import load_patient, check_contradictions, check_drug_entities
from pipeline.inference import (
    merge_entities, _run_extraction, _build_system_prompt, _ensure_model,
    _run_differential_text, _build_differential_prompt,
)
from pipeline.routing import should_escalate, routing_summary
from pipeline.tts import stream_tts
from pipeline.cloud import call_gemini_async, call_gemini_summary_async
from pipeline.alerts import check_alerts
from pipeline.stats import stats

# ── Demo constants ────────────────────────────────────────────────────────────
DEMO_SESSION_ID = "demo"
DEMO_PATIENT_ID = "anna_hakobyan"

# ── Shared state ──────────────────────────────────────────────────────────────
patient = load_patient(DEMO_PATIENT_ID)
session = {
    "entities":   {"symptoms": [], "drugs_mentioned": [], "body_parts": [], "timeline": None, "red_flags": []},
    "alerts_log": [],
}
flagged: set = set()
chunk_index = 0

active_connections: list[WebSocket] = []
system_prompt = _build_system_prompt(patient)
diff_prompt   = _build_differential_prompt(patient)
_local_diff_running = False   # de-bounce: only one differential task at a time

# ── Lifespan ──────────────────────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

    audio_stream.start(loop)
    logger.info("[STARTUP] Loading Cactus model (blocks until ready)...")
    await loop.run_in_executor(None, _ensure_model)
    logger.info("[STARTUP] Model ready — pipeline starting")

    pipeline_task = asyncio.create_task(_audio_pipeline(), name="audio-pipeline")
    logger.info(f"[STARTUP] Demo session ready — patient: {patient.name if patient else 'none'}")
    try:
        yield
    finally:
        pipeline_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pipeline_task
        await audio_stream.stop()
        logger.info("Shutdown complete.")


app = FastAPI(title="Doccy Co-pilot — Demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Broadcast helper ──────────────────────────────────────────────────────────

async def broadcast(payload: dict):
    text = json.dumps(payload)
    dead = []
    for ws in list(active_connections):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_connections.remove(ws)


# ── Cloud task (non-blocking) ─────────────────────────────────────────────────

async def _cloud_task(entities_snapshot: dict, latest_transcript: str, reason: str):
    t0 = time.perf_counter()
    try:
        differential = await call_gemini_async(entities_snapshot, patient, latest_transcript)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        stats.record_cloud(t0)
        logger.info(f"[CLOUD] Gemini responded in {elapsed_ms:.0f}ms (reason={reason})")
        await broadcast({
            "event": "alert",
            "source": "cloud",
            "session_id": DEMO_SESSION_ID,
            "timestamp": datetime.utcnow().isoformat(),
            "escalation_reason": reason,
            "level": differential.get("urgency", "routine"),
            "id": f"cloud-{chunk_index}",
            "title": "Cloud Differential",
            "body": json.dumps(differential.get("differentials", [])),
        })
        question = differential.get("suggested_question")
        if question:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, stream_tts, question)
            logger.info(f"[TTS] speaking: {question!r}")
    except Exception as e:
        logger.error(f"Cloud differential failed: {e}", exc_info=True)


# ── On-device differential task ──────────────────────────────────────────────

async def _local_diff_task(entities_snapshot: dict):
    global _local_diff_running
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, _run_differential_text, entities_snapshot, diff_prompt
        )
        await broadcast({
            "event":      "local_differential",
            "session_id": DEMO_SESSION_ID,
            "timestamp":  datetime.utcnow().isoformat(),
            "source":     "on_device",
            "level":      result.get("urgency", "routine"),
            "data":       result,
        })
        question = result.get("suggested_question")
        if question:
            loop.run_in_executor(None, stream_tts, question)
            logger.info(f"[TTS] speaking: {question!r}")
    except Exception as e:
        logger.error(f"[LOCAL DIFF] failed: {e}", exc_info=True)
    finally:
        _local_diff_running = False


# ── Audio pipeline ────────────────────────────────────────────────────────────

async def _audio_pipeline():
    global chunk_index, _local_diff_running
    logger.info("Audio pipeline task running.")
    loop = asyncio.get_running_loop()

    try:
        STALE_THRESHOLD_S = 6.0  # drop chunk if it waited longer than this

        while True:
            t_sealed, chunk = await audio_stream.get_chunk()
            t_now = time.perf_counter()
            queue_wait_ms = (t_now - t_sealed) * 1000
            chunk_dur = len(chunk) / 16000

            # Drop chunks that have been waiting too long — they are outdated
            if queue_wait_ms > STALE_THRESHOLD_S * 1000:
                stats.chunks_dropped += 1
                logger.warning(
                    f"[PIPELINE] DROP chunk {chunk_index}: stale by {queue_wait_ms:.0f}ms "
                    f"({chunk_dur:.2f}s audio) — inference can't keep up"
                )
                chunk_index += 1
                continue

            stats.chunk_arrived(queue_wait_ms)
            logger.info(
                f"[PIPELINE] chunk {chunk_index}: {chunk_dur:.2f}s audio, "
                f"queue_wait={queue_wait_ms:.0f}ms, "
                f"{len(active_connections)} client(s)"
            )

            # ── On-device inference ───────────────────────────────────────────
            t_inf = time.perf_counter()
            logger.info(f"[INFERENCE] START chunk={chunk_index} audio={chunk_dur:.2f}s")
            try:
                transcript_text, new_entities = await loop.run_in_executor(
                    None, _run_extraction, chunk, system_prompt
                )
            except Exception as e:
                logger.error(f"[INFERENCE] ERROR chunk={chunk_index}: {e}", exc_info=True)
                chunk_index += 1
                continue
            inf_ms = (time.perf_counter() - t_inf) * 1000
            stats.record_inference(t_inf)
            logger.info(
                f"[INFERENCE] END chunk={chunk_index} latency={inf_ms:.0f}ms "
                f"transcript={transcript_text[:80]!r}"
            )
            logger.info(f"[TIMING] entities: {new_entities}")

            ts = datetime.utcnow().isoformat()

            # ── Broadcast transcript + entities ───────────────────────────────
            t_disp = time.perf_counter()
            if transcript_text:
                await broadcast({"event": "transcript", "session_id": DEMO_SESSION_ID,
                                 "timestamp": ts, "text": transcript_text,
                                 "speaker": "unknown"})
            await broadcast({"event": "entities", "session_id": DEMO_SESSION_ID,
                             "timestamp": ts, "data": new_entities})

            if not new_entities:
                stats.record_routing(False)
                chunk_index += 1
                continue

            prev_symptom_count = len(session["entities"].get("symptoms", []))
            merge_entities(session["entities"], new_entities)
            new_symptom_count = len(session["entities"].get("symptoms", []))
            symptom_added = new_symptom_count > prev_symptom_count

            await broadcast({"event": "session_entities", "session_id": DEMO_SESSION_ID,
                             "timestamp": ts, "data": session["entities"]})

            # ── Rule checks ───────────────────────────────────────────────────
            for a in check_alerts(session["entities"], patient, flagged):
                session["alerts_log"].append(a)
                await broadcast({"event": "alert", "session_id": DEMO_SESSION_ID,
                                 "timestamp": ts, **a})

            for c in check_contradictions(new_entities, patient, session["entities"],
                                          flagged, chunk_index):
                await broadcast({"event": "contradiction", "session_id": DEMO_SESSION_ID,
                                 "timestamp": ts, **c})

            for d in check_drug_entities(new_entities, patient, flagged):
                event_type = "contradiction" if d["type"] == "drug_contradiction" else "alert"
                await broadcast({"event": event_type, "session_id": DEMO_SESSION_ID,
                                 "timestamp": ts, **d})

            disp_ms = (time.perf_counter() - t_disp) * 1000
            stats.record_dispatch(t_disp)

            # ── Routing decision ──────────────────────────────────────────────
            escalate, reason = should_escalate(
                new_entities, chunk_index,
                transcript=transcript_text,
                ehr_loaded=(patient is not None),
            )
            stats.record_routing(escalate, reason)

            logger.info(
                f"[TIMING] chunk={chunk_index} "
                f"queue_wait={queue_wait_ms:.0f}ms "
                f"inference={inf_ms:.0f}ms "
                f"dispatch={disp_ms:.0f}ms "
                f"end_to_end={queue_wait_ms + inf_ms + disp_ms:.0f}ms "
                f"routing={'CLOUD('+reason+')' if escalate else 'LOCAL'}"
            )

            # ── Differential diagnosis — triggered by new symptom, routed by 7-layer ──
            # Minimum 3 accumulated symptoms required before any differential fires.
            MIN_SYMPTOMS_FOR_DIFF = 3
            if symptom_added and new_symptom_count >= MIN_SYMPTOMS_FOR_DIFF and not _local_diff_running:
                _local_diff_running = True
                if escalate:
                    logger.info(
                        f"[DIFF] {new_symptom_count} symptoms — routing to CLOUD "
                        f"(reason={reason})"
                    )
                    asyncio.create_task(
                        _cloud_task(dict(session["entities"]), transcript_text, reason)
                    )
                else:
                    logger.info(
                        f"[DIFF] {new_symptom_count} symptoms — routing to ON-DEVICE"
                    )
                    asyncio.create_task(
                        _local_diff_task(dict(session["entities"])),
                        name="local-differential",
                    )
            elif symptom_added and new_symptom_count < MIN_SYMPTOMS_FOR_DIFF:
                logger.info(
                    f"[DIFF] skipped — only {new_symptom_count}/{MIN_SYMPTOMS_FOR_DIFF} "
                    f"symptoms accumulated"
                )

            # Broadcast live stats snapshot after every chunk
            await broadcast({"event": "stats", "session_id": DEMO_SESSION_ID,
                             "timestamp": ts, "data": stats.summary()})

            chunk_index += 1

    except asyncio.CancelledError:
        logger.info("[PIPELINE] cancelled — shutting down.")


# ── REST endpoints ────────────────────────────────────────────────────────────

def _session_payload():
    return {
        "session_id": DEMO_SESSION_ID,
        "patient": patient.name if patient else None,
        "entities": session["entities"],
        "alerts": len(session["alerts_log"]),
    }


@app.get("/session")
def session_get():
    return _session_payload()


@app.get("/session/status")
def session_status():
    return _session_payload()


@app.post("/session/start")
def session_start(patient_id: str = DEMO_PATIENT_ID):
    return {"session_id": DEMO_SESSION_ID, "patient_id": patient_id, "state": "active"}


@app.post("/session/reset")
def session_reset():
    global flagged, chunk_index, _local_diff_running
    _local_diff_running = False
    session["entities"] = {
        "symptoms": [], "drugs_mentioned": [], "body_parts": [],
        "timeline": None, "red_flags": [],
    }
    session["alerts_log"] = []
    flagged = set()
    chunk_index = 0
    stats.reset()
    return {"status": "reset"}


@app.get("/stats")
def get_stats():
    return {**stats.summary(), "routing": routing_summary()}


@app.post("/session/end")
async def session_end():
    try:
        summary = await call_gemini_summary_async(
            session["entities"], patient, session["alerts_log"]
        )
    except Exception as e:
        logger.error(f"Summary failed: {e}", exc_info=True)
        summary = {"error": str(e)}
    await broadcast({
        "event": "session_summary",
        "session_id": DEMO_SESSION_ID,
        "timestamp": datetime.utcnow().isoformat(),
        "data": summary,
    })
    return {"summary": summary}


@app.get("/patients")
def list_patients():
    from pipeline.ehr import load_all_patients
    return load_all_patients()


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WS connected — {len(active_connections)} total")

    # Send initial patient context
    try:
        await websocket.send_text(json.dumps({
            "event": "session_start",
            "session_id": DEMO_SESSION_ID,
            "timestamp": datetime.utcnow().isoformat(),
            "patient_name": patient.name if patient else "Unknown",
            "age": patient.age if patient else None,
            "conditions": patient.diagnoses if patient else [],
            "medications": [f"{m.name} {m.dose}" for m in patient.medications] if patient else [],
            "allergies": [a.substance for a in patient.allergies] if patient else [],
            "flagged_labs": [
                {"test": l.test, "value": l.value, "unit": l.unit, "flag": l.flag}
                for l in (patient.lab_results if patient else [])
                if l.flag
            ],
        }))
    except Exception:
        active_connections.remove(websocket)
        return

    # Block until the client disconnects. Backend pushes via broadcast();
    # receive() here is only to detect the disconnect event — not for data.
    # asyncio.wait_for + receive_text() was cancelling the coroutine on every
    # 30s timeout, leaving the WebSocket receive buffer dirty and causing an
    # immediate close on the next iteration (the reconnect loop the client saw).
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info(f"WS disconnected — {len(active_connections)} remaining")
