"""One-click runner to start both FastAPI backend and Next.js frontend for local preview."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

WEB_DIR = ROOT / "apps" / "web"


def main() -> None:
    print("=" * 65)
    print("  US & Australia Job Market Analytics Platform - One-Click Preview")
    print("=" * 65)

    # 1. Environment variables for SQLite preview mode
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite+pysqlite:///./.preview.db"
    env["AUTO_CREATE_TABLES"] = "true"
    env["API_BASE_URL"] = "http://127.0.0.1:8010"
    env["NEXT_PUBLIC_API_BASE_URL"] = "http://127.0.0.1:8010"

    # Auto-seed if database doesn't exist
    db_file = ROOT / ".preview.db"
    if not db_file.exists() or db_file.stat().st_size == 0:
        print("\n[0/3] First-time setup: Initializing and seeding demo database...")
        try:
            subprocess.run([str(VENV_PYTHON), "-m", "apps.worker.main", "seed-demo"], cwd=str(ROOT), env=env, check=True)
            subprocess.run([str(VENV_PYTHON), "-m", "apps.worker.main", "enrich"], cwd=str(ROOT), env=env, check=True)
        except Exception as exc:
            print(f"Warning during seed: {exc}")

    print("\n[1/3] Starting FastAPI backend on http://127.0.0.1:8010 ...")
    api_cmd = [
        str(VENV_PYTHON),
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8010",
    ]
    api_proc = subprocess.Popen(api_cmd, cwd=str(ROOT), env=env)

    # Wait for API to boot
    time.sleep(2)

    print("[2/3] Starting Next.js frontend on http://localhost:3000 ...")
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    web_proc = subprocess.Popen([npm_cmd, "run", "dev"], cwd=str(WEB_DIR), env=env)

    # Wait for frontend to initialize
    time.sleep(3)

    print("[3/3] Opening web browser at http://localhost:3000 ...")
    try:
        webbrowser.open("http://localhost:3000")
    except Exception:
        pass

    print("\n" + "=" * 65)
    print("  Website is running successfully!")
    print("  - Web UI: http://localhost:3000")
    print("  - Resume Match: http://localhost:3000/match")
    print("  - Market Compare: http://localhost:3000/compare")
    print("  - API Docs: http://127.0.0.1:8010/docs")
    print("  Press Ctrl+C in this terminal to stop both servers.")
    print("=" * 65 + "\n")

    try:
        while True:
            time.sleep(1)
            if api_proc.poll() is not None or web_proc.poll() is not None:
                break
    except KeyboardInterrupt:
        print("\nShutting down servers...")
    finally:
        api_proc.terminate()
        web_proc.terminate()
        try:
            api_proc.wait(timeout=3)
            web_proc.wait(timeout=3)
        except Exception:
            api_proc.kill()
            web_proc.kill()
        print("Servers stopped cleanly.")


if __name__ == "__main__":
    main()
