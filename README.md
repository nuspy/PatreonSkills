# Patreon Creator Skill

A powerful, **model-agnostic** MCP (Model Context Protocol) server that gives any AI agent deep capabilities for managing and growing a Patreon creator page.

Works with **any MCP-compatible agent**: Hermes, OpenClaw, Claude, GPT-4, Llama, Mistral, and more.

## Features

| Category | Capabilities |
|---|---|
| 📊 **Campaign Analytics** | Revenue breakdown, tier analysis, goal tracking, growth strategy |
| 👥 **Supporter Analytics** | Demographics, churn detection, cohort analysis, LTV, segmentation |
| 📝 **Content Tools** | Post analysis, draft templates, media prompts, content calendar |
| 🔍 **Competitor Intel** | Page scraping, tier comparison, trend analysis, web research |
| 💬 **Comment Management** | RAG-powered responses, bulk reply via browser automation |
| 🧠 **Knowledge Base** | ChromaDB RAG with local embeddings (no API key needed) |
| 🔔 **Webhook Management** | Full CRUD for Patreon event webhooks |
| 📈 **Reporting** | Monthly summaries, exports, revenue forecasting |
| 🤖 **Automation** | Post publishing via Playwright browser automation |

## Architecture: Model-Agnostic Design

This skill is designed as a **pure MCP tool server** — it handles:
- Fetching and structuring data from the Patreon API
- RAG retrieval from the local knowledge base
- Web scraping for competitor intelligence
- Browser automation for write operations

For AI generation tasks (post drafts, strategy reports, comment responses), the skill returns **structured data + prompt templates** that your agent uses with its own model. No hardcoded LLM provider.

**Optional**: Configure `LLM_BASE_URL` to use LiteLLM for autonomous batch preprocessing (sentiment analysis, classification) with any model — Ollama, LM Studio, OpenAI-compatible endpoints.

## Installation

### Prerequisites
- Python 3.11+
- A Patreon Creator Access Token ([get it here](https://www.patreon.com/portal/registration/register-clients))

### Setup

```bash
# Clone the repository
git clone https://github.com/nuspy/patreonskills
cd patreonskills

# Install dependencies
pip install -r scripts/requirements.txt

# Install Playwright browsers (only needed for automation features)
playwright install chromium

# Configure credentials
cp .env.example .env
# Edit .env and add your PATREON_ACCESS_TOKEN
```

### Configure your MCP client

Add to your MCP client config (e.g., `mcp_settings.json`, `claude_desktop_config.json`, `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "patreon-creator-skill": {
      "command": "python",
      "args": ["-m", "scripts.mcp_server"],
      "cwd": "/path/to/patreonskills",
      "env": {
        "PATREON_ACCESS_TOKEN": "your_token_here"
      }
    }
  }
}
```

Or run directly for development:
```bash
mcp dev scripts/mcp_server.py
```

## Configuration

See `.env.example` for all available options. Minimum required:

```env
PATREON_ACCESS_TOKEN=your_creator_access_token
```

### Optional LLM for autonomous preprocessing

```env
# Connect to any OpenAI-compatible endpoint
LLM_BASE_URL=http://localhost:11434   # Ollama
LLM_MODEL=hermes3                     # Any available model
LLM_API_KEY=                          # Empty for local Ollama
```

## Available Tools (52 total)

### 🔐 Authentication & Setup
- `patreon_get_identity` — Authenticated creator profile
- `patreon_check_connection` — Verify API credentials
- `patreon_authenticate` — OAuth2 flow

### 📊 Campaign Intelligence
- `campaign_get_overview` — MRR, patron count, campaign stats
- `campaign_analyze_tiers` — Tier structure with revenue analysis
- `campaign_track_goals` — Goal progress and completion
- `campaign_revenue_breakdown` — Detailed MRR by tier
- `campaign_suggest_tier_optimization` — Data + prompt for tier optimization
- `campaign_generate_growth_strategy` — Data + prompt for growth strategy

### 👥 Supporter Analytics
- `members_fetch_all` — Complete member list with pagination
- `members_analyze_demographics` — Tier, tenure, LTV statistics
- `members_detect_churn_risk` — At-risk member identification
- `members_cohort_analysis` — Retention by cohort
- `members_segment` — Segment by tier/tenure/status
- `members_get_top_supporters` — Highest value patrons
- `members_language_analysis` — Language distribution
- `members_geographic_analysis` — Geographic distribution
- `members_recent_activity` — New joins, upgrades, cancellations
- `members_ai_insights` — Data + prompt for AI-powered insights

### 📝 Content & Posts
- `posts_get_analytics` — Post performance analysis
- `posts_fetch_content` — Retrieve post content
- `posts_generate_draft` — Structured prompt for post generation
- `posts_generate_with_media` — Draft + image/video generation prompts
- `posts_optimize_for_engagement` — Data + prompt for optimization
- `posts_suggest_content_calendar` — Data + prompt for content calendar
- `posts_draft_and_review` — Prepare post for publishing
- `posts_publish_via_browser` — Auto-publish with Playwright

### 🔍 Competitor Intelligence
- `competitor_analyze_patreon_page` — Scrape competitor page
- `competitor_compare_tiers` — Tier structure comparison
- `competitor_track_posting_frequency` — Posting cadence analysis
- `competitor_search_web` — Google/Bing search for competitor intel
- `competitor_monitor_social` — Social media trend monitoring
- `competitor_generate_strategy` — Data + prompt for competitive strategy

### 💬 Comment Management
- `comments_fetch_recent` — Get recent post comments
- `comments_generate_response` — RAG context + prompt for responses
- `comments_bulk_respond` — Playwright batch comment replies
- `comments_analyze_sentiment` — Comments + prompt for sentiment analysis

### 🧠 Knowledge Base
- `kb_index_campaign` — Index all campaign posts in ChromaDB
- `kb_add_document` — Add FAQ, brand voice, custom doc
- `kb_search` — Semantic search
- `kb_list_documents` — List indexed documents
- `kb_delete_document` — Remove document

### 🔔 Webhooks
- `webhooks_list` — List configured webhooks
- `webhooks_create` — Create webhook (members:*, posts:*)
- `webhooks_update` — Update webhook config
- `webhooks_delete` — Delete webhook

### 📈 Reports & Monitoring
- `report_monthly_summary` — Complete monthly report
- `report_export_members` — Export member list CSV/JSON
- `report_growth_analysis` — Growth metrics
- `report_revenue_forecast` — Revenue projection data
- `report_competitive_benchmark` — Benchmark vs analyzed competitors
- `monitor_rss_trends` — RSS feed trend monitoring

## Known API Limitations

The Patreon API v2 is **read-only** for most resources:
- Posts, campaigns, tiers, and benefits cannot be created/edited via API
- Comment management is not available via API
- Gifted memberships are not exposed

This skill uses **Playwright browser automation** for write operations. Set `PATREON_EMAIL` and `PATREON_PASSWORD` to enable automation features.

## License

Apache 2.0 — See [LICENSE.txt](LICENSE.txt)
