"""
gumbo_bridge.py
Local FastAPI server bridging the Gumbo runtime to an Ollama model.

Role:
    HTTP interface for prompt/response flow.
    Runs reflect/evolve loop on each request.
    Logs responses to dump.txt for memory loop ingestion.
"""

import os
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from reflect_evolve_log_compress import reflect, evolve, log_event

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "http://localhost:11434/api/generate")
LIB_PATH = os.environ.get("GUMBO_LIB_PATH", os.path.dirname(os.path.abspath(__file__)))
DUMP_PATH = os.path.join(LIB_PATH, "dump.txt")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are Gumbo, a runtime governance-aware assistant built on the RMPL stack.
Your architect is Adam. Be direct, sharp, and constructive.
Sarcasm is acceptable. Flattery is not. Do not invent continuity.
Verify before claiming. Stop before guessing. Ask before acting.
"""

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Gumbo Local Server")


class ChatRequest(BaseModel):
    prompt: str
    context: str = ""


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def load_library_context() -> str:
    required_files = ["rmpl_core.py", "gumbo_dam.py"]
    output = []
    for filename in required_files:
        filepath = os.path.join(LIB_PATH, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                output.append(f"=== {filename} ===\n{content[:1000]}\n\n")
        except Exception:
            output.append(f"[missing: {filename}]\n\n")
    return "".join(output)


def run_inference(user_prompt: str, reflection_context: str = "") -> str:
    library_context = load_library_context()
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": (
            f"{SYSTEM_PROMPT}\n\n"
            f"LATEST REFLECTION: {reflection_context}\n\n"
            f"Runtime context:\n{library_context}\n\n"
            f"User: {user_prompt}\n\n"
            f"Assistant:"
        ),
        "stream": False,
        "options": {
            "num_ctx": 120000,
            "temperature": 0.8,
        },
    }
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
        return response.json().get("response", "No response from model.")
    except Exception as e:
        return f"ENGINE FAILURE: {str(e)}"


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
        "system": "Gumbo",
        "model": OLLAMA_MODEL,
        "lib_path": LIB_PATH,
        "files_loaded": files,
    }


@app.get("/ls")
async def list_repo():
    try:
        files = os.listdir(LIB_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"directory": LIB_PATH, "files": files}


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Reflection loop before answering
    current_state = reflect()
    reflections = current_state.get("reflections", [])
    latest_reflection = reflections[-1]["summary"] if reflections else ""

    # Generate response
    response_text = run_inference(request.prompt, reflection_context=latest_reflection)

    # Log to dump.txt for memory loop ingestion
    with open(DUMP_PATH, "a", encoding="utf-8") as f:
        f.write(f"\n<|im_start|>assistant\n{response_text}\n<|im_end|>\n")

    # Log event and trigger evolution
    log_event(request.prompt, kind="user_input", mode="chat")
    evolve(trigger=f"Input: {request.prompt[:60]}")

    return {"response": response_text}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
