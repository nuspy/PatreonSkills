"""Patreon Creator Skill — MCP Server Entry Point.

Model-agnostic MCP server for Patreon creator management.
Works with any MCP-compatible agent: Hermes, OpenClaw, Claude, GPT, Llama, etc.

Usage:
    # Development / testing
    mcp dev scripts/mcp_server.py

    # Production (add to MCP client config)
    python -m scripts.mcp_server

Required:
    PATREON_ACCESS_TOKEN environment variable

Optional:
    LLM_BASE_URL, LLM_MODEL, LLM_API_KEY  (model-agnostic preprocessing)
    GOOGLE_SEARCH_API_KEY, GOOGLE_SEARCH_CX, BING_SEARCH_API_KEY
    PATREON_EMAIL, PATREON_PASSWORD  (browser automation)

See .env.example for full configuration reference.
"""

import sys
from pathlib import Path

# Ensure the project root is on the Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP

from scripts.tools import (
    campaign_tools,
    member_tools,
    content_tools,
    competitor_tools,
    automation_tools,
    webhook_tools,
    rag_tools,
    reporting_tools,
)

# ── Initialize MCP Server ──
mcp = FastMCP(
    name="patreon-creator-skill",
    instructions="""
Patreon Creator Skill — 52 tools for professional Patreon creator management.

This skill is model-agnostic: tools return structured data and prompt templates
that you use with your own model. No hardcoded LLM provider.

Capabilities:
  🔐 Authentication: patreon_get_identity, patreon_check_connection
  📊 Campaign: campaign_get_overview, campaign_analyze_tiers, campaign_track_goals,
             campaign_revenue_breakdown, campaign_suggest_tier_optimization,
             campaign_generate_growth_strategy
  👥 Members: members_fetch_all, members_analyze_demographics, members_detect_churn_risk,
            members_cohort_analysis, members_segment, members_get_top_supporters,
            members_language_analysis, members_geographic_analysis,
            members_recent_activity, members_ai_insights
  📝 Content: posts_get_analytics, posts_fetch_content, posts_generate_draft,
            posts_generate_with_media, posts_optimize_for_engagement,
            posts_suggest_content_calendar, posts_draft_and_review,
            posts_publish_via_browser
  🔍 Competitor: competitor_analyze_patreon_page, competitor_analyze_multiple_pages,
               competitor_compare_tiers, competitor_track_posting_frequency,
               competitor_search_web, competitor_search_patreon_creators,
               competitor_generate_strategy
  💬 Comments: comments_fetch_recent, comments_generate_response,
             comments_bulk_respond, comments_analyze_sentiment
  🧠 Knowledge Base: kb_index_campaign, kb_add_document, kb_search,
                   kb_list_documents, kb_delete_document
  🔔 Webhooks: webhooks_list, webhooks_create, webhooks_update, webhooks_delete
  📈 Reports: report_monthly_summary, report_export_members, report_growth_analysis,
            report_revenue_forecast, report_competitive_benchmark, monitor_rss_trends

Setup: Set PATREON_ACCESS_TOKEN environment variable.
Docs: https://github.com/nuspy/patreonskills
""",
)

# ── Register all tool modules ──
campaign_tools.register(mcp)
member_tools.register(mcp)
content_tools.register(mcp)
competitor_tools.register(mcp)
automation_tools.register(mcp)
webhook_tools.register(mcp)
rag_tools.register(mcp)
reporting_tools.register(mcp)


if __name__ == "__main__":
    mcp.run()
