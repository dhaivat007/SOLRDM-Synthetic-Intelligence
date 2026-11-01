#!/usr/bin/env python3
"""Record live research API evidence; network restrictions are explicit results."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solrdm_pi.tools import ToolError, execute_tool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="JSON evidence file to write")
    args = parser.parse_args()
    checks = []
    failed = False
    for name, query, field in (("research_papers", "solar cell efficiency", "papers"),
                               ("search_encyclopedia", "Raspberry Pi", "articles")):
        try:
            receipt = execute_tool(name, {"query": query})
            records = receipt.get("data", {}).get(field)
            if (receipt.get("tool") != name or receipt.get("status") != "completed"
                    or not isinstance(records, list) or len(records) > 5
                    or not isinstance(receipt.get("sources"), list)
                    or not isinstance(receipt.get("assumptions"), list)):
                raise ValueError("The live research tool returned an invalid receipt.")
            checks.append({"tool": name, "status": "completed" if records else "no_results",
                           "record_count": len(records), "receipt": receipt})
            print(f"{name}: live API returned {len(records)} records", flush=True)
        except ToolError as error:
            # An external service can reject CI runner traffic, time out, or
            # change its response. Preserve that limitation instead of falsely
            # treating a mocked response as successful online research.
            checks.append({"tool": name, "status": "unavailable", "error": str(error),
                           "limitation": "Live source access was not verified for this tool in this run."})
            print(f"{name}: live source unavailable: {error}", flush=True)
        except Exception as error:
            failed = True
            checks.append({"tool": name, "status": "failed", "error": type(error).__name__ + ": " + str(error)})
            print(f"{name}: unexpected failure ({type(error).__name__})", flush=True)
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(),
                "test": "live fixed-endpoint research requests; no model inference",
                "all_sources_verified": all(item["status"] == "completed" for item in checks),
                "checks": checks,
                "limitations": "Publication metadata and encyclopedia snippets are not full papers, exhaustive research, or verification of scientific claims."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
