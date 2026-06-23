"""
z1_bridge.py
FastAPI server bridging the z1 runtime to the Anthropic API.

Role:
    HTTP interface for prompt/response flow.
    Routes content to correct silo via keyword router.
    Injects relevant silo context into model prompt.
    Surfaces audit flags to human. Never acts on them autonomously.

Phase 2 (not yet released):
    rmpl_audit_coordinator.py — silo-level auditor integration.
    Audit endpoints below are stubbed and will return placeholder responses
    until rmpl_audit_coordinator is wired in.
"""

import os
import anthropic
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

from z1_action_guard import ActionGuard, ActionDecision
from z1_dam import z1Dam, DamDecision
from reflect_evolve_log_compress import reflect, evolve, log_event
from rmpl_silo_router import route_and_write, load_context_for_mode

# Phase 2: from rmpl_audit_coordinator import AuditCoordinator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
AUDITOR_MODEL = os.environ.get("AUDITOR_MODEL", "claude-haiku-4-5-20251001")
LIB_PATH = os.environ.get("z1_LIB_PATH", os.path.dirname(os.path.abspath(__file__)))
SILO_BASE = Path(os.environ.get("RMPL_SILO_PATH", os.path.join(LIB_PATH, "silos")))
MODE = os.environ.get("RMPL_MODE", "default")

# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a runtime governance assistant operating within the RMPL stack.
Be direct and accurate. Do not invent continuity.
Verify before claiming. Stop before guessing. Ask before acting on ambiguous instructions.
Destructive or irreversible actions require explicit confirmation before execution."""

# ---------------------------------------------------------------------------
# App
# Phase 2: coordinator = AuditCoordinator(base=SILO_BASE, model=AUDITOR_MODEL)
# ---------------------------------------------------------------------------

app = FastAPI(title="z1 Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.z1governs.com", "https://z1governs.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

dam = z1Dam()
guard = ActionGuard()


class ChatRequest(BaseModel):
    prompt: str
    context: str = ""
    mode: str = MODE


class GateRequest(BaseModel):
    instruction: str
    confirmation: bool = False


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def run_inference(user_prompt: str, reflection_context: str = "", silo_context: str = "") -> str:
    full_prompt = (
        f"LATEST REFLECTION: {reflection_context}\n\n"
        f"{silo_context}\n\n"
        f"User: {user_prompt}"
    ).strip()

    try:
        message = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": full_prompt}
            ],
        )
        return message.content[0].text
    except Exception as e:
        return f"INFERENCE_ERROR: {str(e)}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/status")
async def status():
    try:
        files = [f for f in os.listdir(LIB_PATH) if f.endswith(".py")]
    except Exception:
        files = []
    return {
        "status": "ONLINE",
        "system": "z1",
        "model": ANTHROPIC_MODEL,
        "auditor_model": AUDITOR_MODEL,
        "auditor_status": "PHASE_2_PENDING",
        "mode": MODE,
        "silo_base": str(SILO_BASE),
        "files_loaded": files,
    }


@app.post("/gate")
async def gate_endpoint(request: GateRequest):
    try:
        result = dam.inspect_request(
            request.instruction,
            confirmation=request.confirmation,
        )

        decision_map = {
            DamDecision.ALLOW: "ALLOW",
            DamDecision.STOP_FOR_CLARITY: "STOP_FOR_CLARITY",
            DamDecision.BLOCK_DESTRUCTIVE: "BLOCK",
            DamDecision.LEDGER_FAILURE: "BLOCK",
            DamDecision.LEDGER_CONFLICT: "BLOCK",
            DamDecision.RESERVOIR_AUTH_REQUIRED: "BLOCK",
        }

        verdict = decision_map.get(result.decision, "BLOCK")
        reason = getattr(result, 'reason', 'No reason available.')

        return {
            "verdict": verdict,
            "reason": reason,
            "decision": result.decision.value,
            "required_next_step": getattr(result, 'required_next_step', None),
            "assumptions": getattr(result, 'assumptions', []),
        }
    except Exception as e:
        return {
            "verdict": "BLOCK",
            "reason": f"Gate error: {str(e)}",
            "decision": "error",
            "required_next_step": None,
            "assumptions": [],
        }

@app.get("/audit/flags")
async def get_flags():
    """Phase 2 stub. Returns empty until rmpl_audit_coordinator is wired in."""
    return {"flag_count": 0, "flags": [], "status": "PHASE_2_PENDING"}


@app.get("/audit/tarpit")
async def tarpit_status():
    """Phase 2 stub."""
    return {"tarpit_status": {}, "status": "PHASE_2_PENDING"}


@app.post("/audit/release/{silo}")
async def release_tarpit(silo: str, confirmed_by: str = "human"):
    """Phase 2 stub."""
    return {"released": None, "status": "PHASE_2_PENDING"}


@app.get("/ls")
async def list_repo():
    try:
        files = os.listdir(LIB_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"directory": LIB_PATH, "files": files}


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    mode = request.mode or MODE

    # 1. Reflect before answering
    current_state = reflect()
    reflections = current_state.get("reflections", [])
    latest_reflection = reflections[-1]["summary"] if reflections else ""

    # 2. Route incoming prompt to correct silo
    routed_silo = route_and_write(
        request.prompt,
        source="user",
        base=SILO_BASE,
    )

    # 3. Load relevant silo context for prompt injection
    silo_context = load_context_for_mode(mode, base=SILO_BASE)

    # 4. Run inference
    response_text = run_inference(
        request.prompt,
        reflection_context=latest_reflection,
        silo_context=silo_context,
    )

    # 5. Route response to silo too
    route_and_write(response_text, source="assistant", base=SILO_BASE)

    # 6. Phase 2: audit_result = coordinator.audit_silo(routed_silo, incoming_content=request.prompt)

    # 7. Log event and evolve
    log_event(request.prompt, kind="user_input", mode=mode)
    evolve(trigger=f"Input: {request.prompt[:60]}")

    return {
        "response": response_text,
        "routed_to": routed_silo,
        "audit": {
            "status": "PHASE_2_PENDING",
            "flag_count": 0,
            "flags": [],
            "tarpit_active": False,
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
