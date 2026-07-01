"""Command-line entry point for locusview.

Phase 0 placeholder: proves the console-script wiring end to end. It grows real
subcommands (ingest, serve, ...) in Phase 1.
"""

from __future__ import annotations

import argparse

from locusview import __version__


def main(argv: list[str] | None = None) -> int:
    """Run the locusview CLI. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="locusview",
        description="A searchable home for publicly available QTL data.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"locusview {__version__}",
    )
    parser.parse_args(argv)
    print(
        "locusview is in Phase 0 (foundation). There is no portal yet — "
        "see docs/product/roadmap.md for what's coming in Phase 1."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
