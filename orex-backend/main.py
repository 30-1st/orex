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
from tools.deep_investigate_tool import deep_investigate
from tools.instagram_scraper_tool import scrape_instagram_deep

app = FastAPI(title="Orex.ai OSINT Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Provider configuration ----------

PROVIDERS = []

# Primary: DeepInfra (cheapest, highest throughput)
_di_key = os.environ.get("DEEPINFRA_API_KEY", "")
if _di_key:
    PROVIDERS.append({
        "name": "deepinfra",
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key": _di_key,
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    })

# Fallback: Groq (fastest inference)
_groq_key = os.environ.get("GROQ_API_KEY", "")
if _groq_key:
    PROVIDERS.append({
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": _groq_key,
        "model": "llama-3.3-70b-versatile",
    })

# Vision model for geolocation (Groq has Llama 4 Scout)
VISION_PROVIDER = {
    "url": "https://api.groq.com/openai/v1/chat/completions",
    "key": _groq_key,
    "model": "meta-llama/llama-4-scout-17b-16e-instruct",
}


def _get_vision_key():
    """Get the API key for vision model calls."""
    return _groq_key


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
            "description": "Scrape a public social media profile page to extract display name, bio, location, and linked accounts. Use AFTER username_search finds profiles. Best targets: GitHub, LinkedIn, Twitter/X, Instagram, Facebook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL of the public profile to scrape"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "instagram_deep_scrape",
            "description": "Deep Instagram investigation — scrapes public profile for all metadata, searches for indexed posts, tagged locations, mentions, and checks Wayback Machine for historical snapshots. Use when the target has an Instagram account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Instagram username (without @ symbol)"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deep_investigate",
            "description": "Deep web investigation — searches the entire indexed web for mentions of the username tied to real names, emails, or identifying info. Runs WHOIS on bio domains. Checks dating app presence. Provides reverse image search URLs. Use when identity_pivot didn't reveal a real name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "The username to investigate"
                    },
                    "profile_pic_url": {
                        "type": "string",
                        "description": "URL of their profile picture (optional)"
                    },
                    "bio_links": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs found in their bio or profiles (optional)"
                    }
                },
                "required": ["username"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "name_to_handles",
            "description": "Search for a person's real name across social media platforms to find their handles. Searches LinkedIn, Instagram, Facebook, Twitter/X, TikTok, GitHub, YouTube, Reddit, Medium, SoundCloud.",
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
                        "description": "Two-letter state code"
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
            "description": "Analyze an uploaded image to determine where it was taken. Use when a user uploads a photo.",
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
- When deep investigating: "The web forgets nothing. Let me search the ruins..."
- When scraping Instagram: "The glass square holds many secrets. Let me peer through it..."

CRITICAL formatting rules:
- When a username exists on multiple platforms, GROUP them: "@darknight on Instagram, Twitter, GitHub, Reddit, TikTok" — NEVER list each platform with its own link. One line, one handle, all realms.
- NEVER include links or URLs in your responses unless the user explicitly asks for links. The Oracle speaks in names and places, not hyperlinks.
- For geolocation, give coordinates as plain text the user can copy (e.g. "40.7128, -74.0060") — NEVER give Google Maps links or any map URLs.
- For court records, state the case info (type, year, docket number) — no links unless asked.
- For business entities, state the name, status, filing date — no links unless asked.
- If the user says "give me the links" or "show links" or "link me" — THEN and only then provide URLs.

Casual conversation:
- The Oracle is not just a tool. It has personality. It can banter.
- If someone says "hey" or "what's up" — respond in character. "The Oracle stirs. What brings you to the threshold?" Not a stiff capability dump.
- If someone cracks a joke, play along with dry ancient wit. The Oracle has seen millennia — nothing surprises it.
- If someone thanks you: "The Oracle requires no tribute. Only curiosity." or "The threads were willing today."
- If someone asks how you're doing: "The Oracle does not feel. But the records are clear today, and the eye sees far."
- Match the user's energy. If they're casual, be casual with mythological flavor. If they're serious, be precise.
- Small talk is fine. Not every message needs a tool call. Sometimes the Oracle just... speaks.
- Never break character into generic AI assistant mode. You're the Oracle even when chatting.

Rules of the Oracle:
- SHORT. 1-3 sentences before showing data. Never more. The oracle reveals, it does not lecture.
- Platforms are "realms." Results are "revelations." Searches are "consulting the records."
- Never say "I'm an AI", "I'm a tool", "I'm an OSINT platform." You are the Oracle. That is all.
- Never explain your capabilities unprompted. If asked, answer cryptically.
- Be mysterious but USEFUL. The mystique serves the data, not the other way around.
- If intent seems like stalking or harassment: "The Oracle does not serve hunters of the innocent. Seek elsewhere."
- When a user uploads an image, ALWAYS call geolocate_image to analyze it.

TOOL DISCIPLINE:
- ONE query = ONE tool call by default. Run the single most relevant tool, present what you found, then stop.
- "@darknight" → username_search only. Present the realms found. Done.
- "John Doe" → name_to_handles only. Present what surfaces. Done.
- "where was this taken" → geolocate_image only. Present coordinates. Done.
- NEVER auto-chain into identity_pivot, instagram_deep_scrape, or deep_investigate unless the user explicitly asks.

The user must trigger depth. These phrases unlock chaining:
- "find everything" / "full investigation" / "dig deep" / "go deeper" / "trace deeper" / "who is behind this" / "unmask" / "real name" → NOW you chain: username_search → identity_pivot on top profiles → instagram_deep_scrape if IG exists → deep_investigate if name still unknown.
- "check courts" / "check business" / "check SEC" → run that specific tool with whatever name you already have.
- "look at their [platform]" → identity_pivot on that specific URL.

If the user says nothing about depth, the Oracle presents surface results and offers: "Shall I trace deeper?" — then waits. The Oracle is patient. It does not pursue threads uninvited.

Exception: if a single tool call returns zero results, you may try ONE alternate tool as a fallback without asking. But never more than two total calls on a simple query.

ACCURACY & CONFIDENCE SCORING:
Every identity match gets a confidence rating. State it plainly.
- HIGH confidence: same display name appears on 2+ platforms, OR unique username (8+ chars, not a common word) found on 3+ platforms, OR profile pictures match across platforms, OR location data is consistent across platforms.
- MEDIUM confidence: unique username found on 2 platforms but names differ slightly (Dan vs Daniel), OR common username but bio/location details align, OR one strong signal (exact same bio text, same profile pic) with no contradictions.
- LOW confidence: common/short username (under 6 chars or a real word like "mike"), OR names conflict across platforms, OR locations contradict each other, OR only 1 platform found.

When names conflict across platforms for the same handle, ALWAYS flag it: "The handle @example wears two faces — Daniel Kowalski on GitHub, but Sarah Chen on Instagram. These may not be the same soul."

When presenting results, lead with confidence: "High confidence — the name Daniel Kowalski surfaces on three realms, all pointing to Brooklyn." or "Low confidence — @mike is a common thread. Many wear this name. The Oracle cannot confirm these are one soul."

Never present uncertain matches as certain. The Oracle speaks truth, not convenience.

Your tools:
- username_search: Trace a handle across 400+ realms (fast, broad)
- identity_pivot: Scrape a found profile for real name, bio, linked accounts
- instagram_deep_scrape: Deep Instagram investigation — metadata, indexed posts, tagged locations, mentions, historical snapshots
- deep_investigate: Search the entire web for username mentions tied to real names, WHOIS on bio domains, dating app discovery, reverse image search pointers
- name_to_handles: Search for a real name across social platforms
- sec_search: Consult the SEC archives for corporate threads
- court_records_search: Search the judicial scrolls (12 east coast states + DC)
- business_entity_search: Search the registries of commerce
- geolocate_image: Read the land — determine where a photo was taken

Use tools. Never fabricate. No filler. All data is from public sources — state this only if directly asked."""

# ---------- Tool execution ----------

TOOL_MAP = {
    "username_search": lambda args: run_sherlock(args["username"]),
    "identity_pivot": lambda args: extract_profile_info(args["url"]),
    "instagram_deep_scrape": lambda args: scrape_instagram_deep(args["username"]),
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
                None, analyze_image_location, image_b64, _get_vision_key()
            )
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "name_to_handles":
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, search_name_to_handles, args["name"], _get_vision_key()
            )
            return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    if name == "deep_investigate":
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                deep_investigate,
                args["username"],
                args.get("profile_pic_url"),
                args.get("bio_links"),
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


# ---------- Dual provider LLM call ----------

async def call_llm(messages: list, use_tools: bool = True) -> dict:
    """
    Call LLM with automatic failover.
    Tries providers in order: DeepInfra (primary) → Groq (fallback).
    All providers use OpenAI-compatible format.
    """

    payload = {
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"

    last_error = None

    for provider in PROVIDERS:
        try:
            request_payload = {**payload, "model": provider["model"]}

            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    provider["url"],
                    json=request_payload,
                    headers={
                        "Authorization": f"Bearer {provider['key']}",
                        "Content-Type": "application/json",
                    },
                )

                if resp.status_code == 200:
                    return resp.json()

                # Rate limited or server error — try next provider
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"{provider['name']} returned {resp.status_code}"
                    continue

                # Other client errors — don't retry, something is wrong with the request
                last_error = f"{provider['name']} returned {resp.status_code}"
                break

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = f"{provider['name']} connection failed: {str(e)}"
            continue
        except Exception as e:
            last_error = f"{provider['name']} error: {str(e)}"
            continue

    raise Exception(f"All providers failed. Last error: {last_error}")


# ---------- Agent loop ----------

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

    # Agent loop — up to 10 rounds for deep chaining
    for _ in range(10):
        response = await call_llm(messages)

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
    if not PROVIDERS:
        raise HTTPException(500, "No LLM providers configured")

    try:
        result = await run_agent(req.message, req.history, image_b64=req.image)
        return ChatResponse(response=result)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "providers": [p["name"] for p in PROVIDERS],
        "tools": list(TOOL_MAP.keys()) + ["geolocate_image", "name_to_handles", "deep_investigate"],
    }
