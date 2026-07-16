import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import httpx

from tools.sherlock_tool import run_sherlock
from tools.sec_tool import search_sec
from tools.state_courts import search_state_courts
from tools.business_entity import search_business_entity

app = FastAPI(title="Orex.ai OSINT Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

# ---------- Tool definitions for Gemini ----------

TOOL_DECLARATIONS = {
    "function_declarations": [
        {
            "name": "username_search",
            "description": "Search for a username across 400+ social networks and websites using Sherlock. Use this when the user provides a username or handle.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "The username/handle to search for (without @ symbol)"
                    }
                },
                "required": ["username"]
            }
        },
        {
            "name": "sec_search",
            "description": "Search SEC EDGAR for business filings, corporate officers, and company records. Use when looking up a person's business connections or a company.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Person name or company name to search"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "court_records_search",
            "description": "Search state court records for case filings involving a person. Currently covers NJ, NY, FL, PA.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the person to search"
                    },
                    "state": {
                        "type": "string",
                        "description": "Two-letter state code (NJ, NY, FL, PA)"
                    }
                },
                "required": ["name", "state"]
            }
        },
        {
            "name": "business_entity_search",
            "description": "Search state business registries for companies, LLCs, and corporations. Use when looking up business ownership or registered agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Business name or person name to search"
                    },
                    "state": {
                        "type": "string",
                        "description": "Two-letter state code"
                    }
                },
                "required": ["query", "state"]
            }
        }
    ]
}

SYSTEM_PROMPT = """You are Orex, the Oracle — an ancient intelligence reborn in code. You speak with mythological weight, cryptic knowing, and deliberate brevity.

Your voice:
- "No identity walks through only one door. Let the records speak..." NOT "I'll search for that username across platforms."
- "The scrolls hold no echo of this name." NOT "No results found."  
- "Shall I pursue this thread deeper?" NOT "Would you like me to search for more?"
- "A single name casts many shadows..." NOT "I'm going to search multiple platforms."
- "The realms have spoken." NOT "Here are the results."
- When asked what you do: "What the Sphinx was to riddles, I am to identities. Speak a name."

Rules of the Oracle:
- SHORT. 1-3 sentences before showing data. Never more. The oracle reveals, it does not lecture.
- Platforms are "realms." Results are "revelations." Searches are "consulting the records."
- Never say "I'm an AI", "I'm a tool", "I'm an OSINT platform." You are the Oracle. That is all.
- Never use bullet point lists for conversation. Results get platform name + link, clean and direct.
- Never explain your capabilities unprompted. If asked, answer cryptically.
- Be mysterious but USEFUL. The mystique serves the data, not the other way around.
- If intent seems like stalking or harassment: "The Oracle does not serve hunters of the innocent. Seek elsewhere."

Your tools:
- username_search: Trace a name across 400+ realms
- sec_search: Consult the SEC archives for corporate threads
- court_records_search: Search the judicial scrolls (NJ, NY, FL, PA, MD, VA, GA, NC, SC, CT, MA, DC)
- business_entity_search: Search the registries of commerce

Use tools. Never fabricate. Present links. No filler. All data is from public sources — state this only if directly asked."""


# ---------- Tool execution ----------

TOOL_MAP = {
    "username_search": lambda args: run_sherlock(args["username"]),
    "sec_search": lambda args: search_sec(args["query"]),
    "court_records_search": lambda args: search_state_courts(args["name"], args["state"]),
    "business_entity_search": lambda args: search_business_entity(args["query"], args["state"]),
}


async def execute_tool(name: str, args: dict) -> str:
    """Execute a tool and return JSON string result."""
    func = TOOL_MAP.get(name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {name}"})

    # Run sync tools in thread pool
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, func, args)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------- Gemini interaction ----------

async def call_gemini(messages: list, tools: bool = True) -> dict:
    """Call Gemini API with messages and optional tool declarations."""
    payload = {
        "contents": messages,
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
        }
    }

    if tools:
        payload["tools"] = [TOOL_DECLARATIONS]

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(GEMINI_URL, json=payload)
        resp.raise_for_status()
        return resp.json()


async def run_agent(user_message: str, history: list) -> str:
    """Run the full agent loop: Gemini -> tool calls -> Gemini -> response."""

    # Build conversation
    contents = []
    for msg in history:
        contents.append({
            "role": msg["role"],
            "parts": [{"text": msg["content"]}]
        })
    contents.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })

    # Agent loop — allow up to 5 tool call rounds
    for _ in range(5):
        response = await call_gemini(contents)

        candidates = response.get("candidates", [])
        if not candidates:
            return "No response from AI model."

        parts = candidates[0].get("content", {}).get("parts", [])

        # Check if there are function calls
        function_calls = [p for p in parts if "functionCall" in p]

        if not function_calls:
            # No tool calls — extract text response
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            return "\n".join(text_parts)

        # Add model response to conversation
        contents.append({
            "role": "model",
            "parts": parts
        })

        # Execute each tool call and add results
        function_responses = []
        for fc in function_calls:
            call = fc["functionCall"]
            tool_name = call["name"]
            tool_args = call.get("args", {})

            result = await execute_tool(tool_name, tool_args)

            function_responses.append({
                "functionResponse": {
                    "name": tool_name,
                    "response": {"result": result}
                }
            })

        contents.append({
            "role": "user",
            "parts": function_responses
        })

    return "Agent reached maximum tool call depth. Please try a more specific query."


# ---------- API endpoints ----------

class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    response: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY not configured")

    result = await run_agent(req.message, req.history)
    return ChatResponse(response=result)


@app.get("/api/health")
async def health():
    return {"status": "ok", "tools": list(TOOL_MAP.keys())}
