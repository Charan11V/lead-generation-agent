"""CLI runner — same graph as the UI, writes output/sample_output.csv."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from frequency_agent.export import export_leads
from frequency_agent.graph import run_agent

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Frequency lead intelligence agent")
    parser.add_argument(
        "--icp",
        default="Series B+ fintech startups in India that raised in the last 90 days",
    )
    parser.add_argument(
        "--service-line",
        default="exec_search",
        choices=["exec_search", "fractional_cxo", "capital_advisory"],
    )
    args = parser.parse_args()
    openai_key = os.getenv("OPENAI_API_KEY", "")
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not openai_key:
        raise SystemExit("Set OPENAI_API_KEY in .env")

    def on_update(node, state):
        print(f"[{node}] {(state.get('logs') or ['...'])[-1]}")

    result = run_agent(
        icp_text=args.icp,
        service_line=args.service_line,
        openai_key=openai_key,
        tavily_key=tavily_key,
        on_update=on_update,
    )
    if result.get("error"):
        raise SystemExit(result["error"])
    leads = result.get("leads") or []
    csv_path, json_path = export_leads(leads, ROOT / "output")
    print(f"Queued {len(leads)} leads")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
