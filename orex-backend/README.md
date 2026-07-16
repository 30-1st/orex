# Orex.ai — OSINT Agent Backend

Public OSINT research agent. Enter a username, name, or entity — get aggregated results from public sources.

## Tools

| Tool | Source | Coverage |
|------|--------|----------|
| `username_search` | Sherlock | 400+ platforms worldwide |
| `sec_search` | SEC EDGAR | All US federal filings |
| `court_records_search` | State court portals | NJ, NY, FL, PA, MD, VA, GA, NC, SC, CT, MA, DC |
| `business_entity_search` | OpenCorporates + state SOS | Same states + DE |

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app), create new project → "Deploy from GitHub repo"
3. Add environment variable: `GEMINI_API_KEY` = your Google AI Studio key
4. Railway auto-detects the Dockerfile and deploys
5. Your API is live at `https://your-project.up.railway.app`

## Local dev

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
uvicorn main:app --reload
```

## API

**POST /api/chat**
```json
{
  "message": "find profiles for @johndoe",
  "history": []
}
```

**GET /api/health** — status check
