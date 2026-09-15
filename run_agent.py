"""CLI runner — same graph as the UI, writes output/sample_output.csv."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from frequency_agent.export import export_leads
from frequency_agent.graph import run_agent
from frequency_agent.icp import service_line_label

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Frequency lead intelligence agent")
    parser.add_argument(
        "--icp",
        default="Series B+ fintech startups in India that raised in the last 90 days",
        help="Plain-language ICP brief (service line is inferred automatically)",
    )
    args = parser.parse_args()
    openai_key = os.getenv("OPENAI_API_KEY", "")
    # CLI-only: the Streamlit app never reads TAVILY_API_KEY — each user stores their own.
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not openai_key:
        raise SystemExit("Set OPENAI_API_KEY in .env")

    def on_update(node, state):
        print(f"[{node}] {(state.get('logs') or ['...'])[-1]}")

    result = run_agent(
        icp_text=args.icp,
        openai_key=openai_key,
        tavily_key=tavily_key,
        on_update=on_update,
    )
    if result.get("error"):
        raise SystemExit(result["error"])
    leads = result.get("leads") or []
    icp = result.get("icp") or {}
    sl = icp.get("service_line") or result.get("service_line") or ""
    if sl:
        print(f"Inferred service line: {service_line_label(sl)} ({sl})")
    csv_path, json_path = export_leads(leads, ROOT / "output")
    print(f"Queued {len(leads)} leads")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")


if __name__ == "__main__":
    main()
