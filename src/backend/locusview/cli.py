"""Command-line entry point for locusview.

Subcommands:
  (none)   print the current project status.
  serve    run the web application with uvicorn.

More subcommands (e.g. ``ingest``) arrive with the data layer.
"""

from __future__ import annotations

import argparse

from locusview import __version__


def _serve(host: str, port: int) -> int:  # pragma: no cover - thin wrapper around uvicorn
    """Run the web app with uvicorn (not unit-tested; exercised manually / in Docker)."""
    import uvicorn

    from locusview.web import create_app

    uvicorn.run(create_app(), host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the locusview CLI. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="locusview",
        description="A searchable home for publicly available QTL data.",
    )
    parser.add_argument("--version", action="version", version=f"locusview {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="run the web application")
    serve_p.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")

    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve(args.host, args.port)

    print(
        "locusview is in early development (Phase 0/1). Run `locusview serve` to start the "
        "web app, or see docs/product/roadmap.md for what's coming."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
