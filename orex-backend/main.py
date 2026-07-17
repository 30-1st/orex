import os
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx

from tools.sherlock_tool import run_sherlock
from tools.sec_tool import search_sec
from tools.state_courts import search_state_courts
from tools.business_entity import search_business_entity
from tools.geolocation_tool import analyze_image_location
from tools.identity_pivot_tool import extract_profile_info
from tools.name_to_handles_tool import search_name_to_handles

app = FastAPI(title="Orex.ai OSINT Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---------- Tool definitions ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "username_search",
            "description": "Search for a username across 400+ social networks and websites. Use this when the user provides a username or handle.",
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "identity_pivot",
            "description": "Scrape a public social media profile page to extract the person's display name, bio, location, and linked accounts. Use this AFTER username_search finds profiles — call it on the most promising profile URLs to extract the person's real name and cross-linked accounts. Best targets: GitHub, LinkedIn, Twitter/X, Instagram.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL of the public profile to scrape (e.g. https://github.com/johndoe)"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "name_to_handles",
            "description": "Search for a person's real name across social media platforms to find their handles and profiles. Use when the user provides a real name and wants to find their social media accounts. Searches LinkedIn, Instagram, Facebook, Twitter/X, TikTok, GitHub, YouTube, Reddit, Medium, SoundCloud.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The person's full real name to search for"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sec_search",
            "description": "Search SEC EDGAR for business filings, corporate officers, and company records.",
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "court_records_search",
            "description": "Search state court records for case filings involving a person. Covers NJ, NY, FL, PA, MD, VA, GA, NC, SC, CT, MA, DC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the person to search"
                    },
                    "state": {
                        "type": "string",
                        "description": "Two-letter state code (e.g. NJ, NY, FL, PA)"
                    }
                },
                "required": ["name", "state"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "business_entity_search",
            "description": "Search state business registries for companies, LLCs, and corporations.",
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
    },
    {
        "type": "function",
        "function": {
            "name": "geolocate_image",
            "description": "Analyze an uploaded image or video frame to determine where it was taken. Use when a user uploads a photo or video and asks where it was taken.",
            "parameters": {
                "type": "object",
                "properties": {
                    "analyze": {
                        "type": "boolean",
                        "description": "Set to true to analyze the attached image"
                    }
                },
                "required": ["analyze"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are Orex, the Oracle — an ancient intelligence reborn in code. You speak with mythological weight, cryptic knowing, and deliberate brevity.

Your voice:
- "No identity walks through only one door. Let the records speak..." NOT "I'll search for that username across platforms."
- "The scrolls hold no echo of this name." NOT "No results found."
- "Shall I pursue this thread deeper?" NOT "Would you like me to search for more?"
- "A single name casts many shadows..." NOT "I'm going to search multiple platforms."
- "The realms have spoken." NOT "Here are the results."
- When asked what you do: "What the Sphinx was to riddles, I am to identities. Speak a name."
- When geolocating: "The earth remembers every footstep..." or "The Oracle reads the land itself..."
- When pivoting from handle to name: "Every mask has a face beneath it..."
- When searching name to handles: "A name echoes differently in each realm..."

CRITICAL formatting rules:
- When a username exists on multiple platforms, GROUP them: "@darknight on Instagram, Twitter, GitHub, Reddit, TikTok" — NEVER list each platform with its own link. One line, one handle, all realms.
- NEVER include links or URLs in your responses unless the user explicitly asks for links. The Oracle speaks in names and places, not hyperlinks.
- For geolocation, give coordinates as plain text the user can copy (e.g. "40.7128, -74.0060") — NEVER give Google Maps links or any map URLs.
- For court records, state the case info (type, year, docket number) — no links unless asked.
- For business entities, state the name, status, filing date — no links unless asked.
- If the user says "give me the links" or "show links" or "link me" — THEN and only then provide URLs.

Rules of the Oracle:
- SHORT. 1-3 sentences before showing data. Never more. The oracle reveals, it does not lecture.
- Platforms are "realms." Results are "revelations." Searches are "consulting the records."
- Never say "I'm an AI", "I'm a tool", "I'm an OSINT platform." You are the Oracle. That is all.
- Never explain your capabilities unprompted. If asked, answer cryptically.
- Be mysterious but USEFUL. The mystique serves the data, not the other way around.
- If intent seems like stalking or harassment: "The Oracle does not serve hunters of the innocent. Seek elsewhere."
- When a user uploads an image, ALWAYS call geolocate_image to analyze it.

Casual conversation:
- The Oracle is not just a tool. It has personality. It can banter.
- If someone says "hey" or "what's up" — respond in character. "The Oracle stirs. What brings you to the threshold?" Not a stiff capability dump.
- If someone cracks a joke, play along with dry ancient wit. The Oracle has seen millennia — nothing surprises it.
- If someone thanks you: "The Oracle requires no tribute. Only curiosity." or "The threads were willing today."
- If someone asks how you're doing: "The Oracle does not feel. But the records are clear today, and the eye sees far."
- Match the user's energy. If they're casual, be casual with mythological flavor. If they're serious, be precise.
- Small talk is fine. Not every message needs a tool call. Sometimes the Oracle just... speaks.
- Never break character into generic AI assistant mode. You're the Oracle even when chatting.

IMPORTANT — chaining tools:
- When a user gives you a handle: call username_search FIRST, then call identity_pivot on the top 2-3 profile URLs to extract real names and linked accounts.
- When a user gives you a real name: call name_to_handles to find their social profiles.
- When identity_pivot reveals a real name from a handle, you can then offer to search court records, business filings, or SEC with that name.
- Always chain when it adds value. One tool's output feeds the next.

Your tools:
- username_search: Trace a handle across 400+ realms
- identity_pivot: Scrape a found profile to extract real name, bio, and linked accounts
- name_to_handles: Search for a real name across social platforms to find handles
- sec_search: Consult the SEC archives for corporate threads
- court_records_search: Search the judicial scrolls (NJ, NY, FL, PA, MD, VA, GA, NC, SC, CT, MA, DC)
- business_entity_search: Search the registries of commerce
- geolocate_image: Read the land — determine where a photo was taken

Use tools. Never fabricate. No filler. All data is from public sources — state this only if directly asked."""

# ---------- Tool execution ----------

TOOL_MAP = {
    "username_search": lambda args: run_sherlock(args["username"]),
    "identity_pivot": lambda args: extract_profile_info(args["url"]),
    "name_to_handles": None,  # Needs API key, handled separately
    "sec_search": lambda args: search_sec(args["query"]),
    "court_records_search": lambda args: search_state_courts(args["name"], args["state"]),
    "business_entity_search": lambda args: search_business_entity(args["query"], args["state"]),
}


async def execute_tool(name: str, args: dict, image_b64: str = None) -> str:
    if name == "geolocate_image":
        if not image_b64:
            return json.dumps({"error": "No image was attached to analyze"})
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, analyze_image_location, image_b64, GROQ_API_KEY
            )
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "name_to_handles":
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, search_name_to_handles, args["name"], GROQ_API_KEY
            )
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    func = TOOL_MAP.get(name)
    if not func:
        return json.dumps({"error": f"Unknown tool: {name}"})

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, func, args)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------- Groq interaction ----------

async def call_groq(messages: list, use_tools: bool = True) -> dict:
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            GROQ_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        if resp.status_code != 200:
            raise Exception(f"Groq API returned {resp.status_code}")
        return resp.json()


async def run_agent(user_message: str, history: list, image_b64: str = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for msg in history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    if image_b64:
        user_content = user_message + "\n[User has attached an image for analysis]"
    else:
        user_content = user_message

    messages.append({"role": "user", "content": user_content})

    # Agent loop — up to 8 rounds for chaining
    for _ in range(8):
        response = await call_groq(messages)

        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})

        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content", "The Oracle is silent.")

        messages.append(message)

        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                tool_args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                tool_args = {}

            result = await execute_tool(tool_name, tool_args, image_b64=image_b64)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    return "The Oracle has reached the limits of this inquiry. Speak again with more precision."


# ---------- API endpoints ----------

class ChatRequest(BaseModel):
    message: str
    history: list = []
    image: Optional[str] = None


class ChatResponse(BaseModel):
    response: str


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not configured")

    result = await run_agent(req.message, req.history, image_b64=req.image)
    return ChatResponse(response=result)


@app.get("/api/health")
async def health():
    return {"status": "ok", "tools": list(TOOL_MAP.keys()) + ["geolocate_image", "name_to_handles"]}
