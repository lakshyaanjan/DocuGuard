"""Create a tiny Git repository with a deliberate documentation drift for the web UI demo."""

from pathlib import Path
import subprocess
import tempfile


def run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def commit(repository: Path, message: str) -> None:
    subprocess.run(
        [
            "git", "-C", str(repository),
            "-c", "user.name=DocuGuard Demo",
            "-c", "user.email=demo@docuguard.local",
            "commit", "-m", message,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> None:
    repository = Path(tempfile.mkdtemp(prefix="docuguard-web-demo-"))
    run_git(repository, "init")
    (repository / "server.py").write_text(
        "APPLICATION_DEFAULT_PORT = 8000\n",
        encoding="utf-8",
    )
    (repository / "README.md").write_text(
        "# Demo application\n\n"
        "The application listens on port 8000 by default.\n",
        encoding="utf-8",
    )
    run_git(repository, "add", "server.py", "README.md")
    commit(repository, "Create application with port 8000")

    (repository / "server.py").write_text(
        "APPLICATION_DEFAULT_PORT = 9090\n",
        encoding="utf-8",
    )
    run_git(repository, "add", "server.py")
    commit(repository, "Change application port to 9090")

    print("DocuGuard web demo repository created:")
    print(repository)
    print()
    print("Use this path in the web app with comparison reference HEAD~1.")


if __name__ == "__main__":
    main()
