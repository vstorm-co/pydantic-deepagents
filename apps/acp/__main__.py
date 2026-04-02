"""Run the pydantic-deep ACP server.

Usage:
    python -m apps.acp
    python -m apps.acp --model anthropic:claude-sonnet-4-6
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="pydantic-deep ACP server")
    parser.add_argument("--model", default=None, help="Default model")
    parser.add_argument("--cwd", default=None, help="Working directory")
    args = parser.parse_args()

    # Load .env files (manual parsing — no dotenv dependency needed)
    for env_path in [
        Path.home() / ".pydantic-deep" / ".env",
        Path.cwd() / ".pydantic-deep" / ".env",
        Path.cwd() / ".env",
    ]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value

    from acp import run_agent

    from apps.acp.server import AgentSessionContext, DeepAgentACP
    from pydantic_deep import create_deep_agent

    # Auto-detect default model from available API keys
    default_model = args.model or os.environ.get("PYDANTIC_DEEP_MODEL")
    if not default_model:
        if os.environ.get("ANTHROPIC_API_KEY"):
            default_model = "anthropic:claude-sonnet-4-6"
        elif os.environ.get("OPENROUTER_API_KEY"):
            default_model = "openrouter:anthropic/claude-sonnet-4"
        elif os.environ.get("OPENAI_API_KEY"):
            default_model = "openai:gpt-4.1"
        elif os.environ.get("GOOGLE_API_KEY"):
            default_model = "google:gemini-2.5-pro"
        else:
            default_model = "anthropic:claude-sonnet-4-6"  # fallback

    models = [
        {"value": "anthropic:claude-opus-4-6", "name": "Claude Opus 4.6"},
        {"value": "anthropic:claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
        {"value": "anthropic:claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        {"value": "openrouter:anthropic/claude-sonnet-4", "name": "Claude Sonnet 4 (OpenRouter)"},
        {"value": "openrouter:openai/gpt-4.1", "name": "GPT-4.1 (OpenRouter)"},
        {"value": "openrouter:google/gemini-2.5-pro", "name": "Gemini 2.5 Pro (OpenRouter)"},
        {"value": "openai:gpt-4.1", "name": "GPT-4.1"},
        {"value": "google:gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    ]

    def build_agent(ctx: AgentSessionContext):
        return create_deep_agent(
            model=ctx.model or default_model,
            context_discovery=True,
        )

    server = DeepAgentACP(agent=build_agent, models=models)
    asyncio.run(run_agent(server))


if __name__ == "__main__":
    main()
