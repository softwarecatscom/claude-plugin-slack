"""Shared CLI options for all slack-* Python scripts.

Usage in PEP 723 scripts:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from slack_cli_options import COMMON_OPTIONS
"""

from __future__ import annotations

import typer

COMMON_OPTIONS = {
    "verbose": typer.Option(0, "--verbose", "-v", count=True, help="Increase verbosity, repeatable", envvar="VERBOSE"),
    "debug": typer.Option(False, "--debug", help="Enable debug output", envvar="DEBUG"),
    "dry_run": typer.Option(False, "--dry-run", help="Dry run — skip side effects", envvar="DRY_RUN"),
}
