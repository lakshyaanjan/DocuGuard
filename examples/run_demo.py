"""Create a tiny Git repository with stale documentation and run DocuGuard.

Run from the DocuGuard checkout:
  python examples/run_demo.py
  python examples/run_demo.py --llm-mode off
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP = PROJECT_ROOT / "app.py"


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def create_demo_repository(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "server.py").write_text(
        "APPLICATION_DEFAULT_PORT = 8000\n\n"
        "def start_server():\n"
        "    return APPLICATION_DEFAULT_PORT\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "# Server setup\n\n"
        "The HTTP application listens on port 8000 by default.\n\n"
        "## Historical note\n\n"
        "Previously, the application listened on port 8000 before the v2 release.\n",
        encoding="utf-8",
    )
    commands = [
        ["git", "init"],
        ["git", "config", "user.name", "DocuGuard Demo"],
        ["git", "config", "user.email", "demo@docuguard.local"],
        ["git", "add", "."],
        ["git", "commit", "-m", "Initial version with port 8000"],
    ]
    for command in commands:
        result = run(command, root)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Command failed: {command}")

    # Simulate a pull request that changes code but forgets to update the docs.
    (root / "server.py").write_text(
        "APPLICATION_DEFAULT_PORT = 9090\n\n"
        "def start_server():\n"
        "    return APPLICATION_DEFAULT_PORT\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DocuGuard's reproducible drift demo.")
    parser.add_argument("--llm-mode", choices=("auto", "off", "required"), default="auto")
    parser.add_argument("--no-embeddings", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "demo-output",
    )
    args = parser.parse_args(argv)

    args.output = args.output.expanduser().resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docuguard-demo-") as temporary:
        demo_repo = Path(temporary) / "demo-project"
        create_demo_repository(demo_repo)
        html_report = args.output / "docuguard-demo.html"
        json_report = args.output / "docuguard-demo.json"
        command = [
            sys.executable,
            str(APP),
            "--repo", str(demo_repo),
            "--llm-mode", args.llm_mode,
            "--html-out", str(html_report),
            "--json-out", str(json_report),
        ]
        if args.no_embeddings:
            command.append("--no-embeddings")
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        # Exit code 1 is expected: this demo deliberately contains stale docs.
        if result.returncode not in {0, 1}:
            return result.returncode
        if not json_report.is_file() or not html_report.is_file():
            print("Demo reports were not created.", file=sys.stderr)
            return 2

        payload = json.loads(json_report.read_text(encoding="utf-8"))
        likely = [
            item for item in payload.get("findings", [])
            if item.get("status") == "likely_drift"
        ]
        if not likely:
            print(
                "The demo did not detect its intentionally stale current-behavior passage.",
                file=sys.stderr,
            )
            return 3
        print(f"Demo passed: {len(likely)} likely drift finding(s).")
        print(f"HTML report: {html_report}")
        print(f"JSON report: {json_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
