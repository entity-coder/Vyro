"""Vyro - self-update from GitHub.

Checks the latest commit on main of entity-coder/vyro (public repo, no
auth), downloads the source ZIP on user approval, and applies it through a
batch script that runs AFTER the app exits - Windows cannot overwrite a
running .exe. User data (billbook_data/) is never touched.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from zipfile import ZipFile

REPO = "entity-coder/vyro"
BRANCH = "main"
API_COMMIT_URL = "https://api.github.com/repos/%s/commits/%s" % (REPO, BRANCH)
ZIP_URL_TMPL = "https://github.com/%s/archive/{sha}.zip" % REPO
TIMEOUT = 12
USER_AGENT = "Vyro-updater"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def version_file() -> Path:
    return app_dir() / "version.txt"


def local_version():
    try:
        text = version_file().read_text(encoding="utf-8").strip()
        return text or None
    except Exception:
        return None


def save_version(sha: str) -> None:
    try:
        version_file().write_text(str(sha).strip(), encoding="utf-8")
    except Exception:
        pass


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def remote_sha():
    """Latest commit SHA on main, or None when offline / on any failure."""
    try:
        data = _get_json(API_COMMIT_URL)
        return data.get("sha") if isinstance(data, dict) else None
    except Exception:
        return None


def check_update():
    """Returns (status, sha).

    status is one of:
      "available" - a newer commit exists, banner the user
      "uptodate"  - already on the latest commit
      "baseline"  - no version.txt yet; recorded current SHA, treat as current
      "offline"   - could not reach GitHub; silently skip
    """
    sha = remote_sha()
    if not sha:
        return ("offline", None)
    current = local_version()
    if not current:
        save_version(sha)
        return ("baseline", sha)
    if current.strip() == str(sha).strip():
        return ("uptodate", sha)
    return ("available", sha)


def download_and_stage(sha, progress=None):
    """Download the source ZIP for *sha* and extract it into
    <app_dir>/update_staging. Returns the staging dir. Raises on failure."""
    base = app_dir()
    staging = base / "update_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="billbook_update_"))
    try:
        zf = tmp / "src.zip"
        req = urllib.request.Request(ZIP_URL_TMPL.format(sha=sha),
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp, \
                open(zf, "wb") as fh:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            got = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if progress and total:
                    try:
                        progress(min(got / total, 1.0))
                    except Exception:
                        pass
        with ZipFile(zf) as z:
            z.extractall(tmp)
        roots = [d for d in tmp.iterdir() if d.is_dir()]
        if not roots:
            raise RuntimeError("Downloaded ZIP has no top-level folder.")
        root = roots[0]
        if not (root / "main.py").exists():
            raise RuntimeError("Downloaded update is missing main.py - aborting.")
        for item in root.iterdir():
            dest = staging / item.name
            if item.is_dir():
                shutil.copytree(
                    item, dest,
                    ignore=shutil.ignore_patterns("__pycache__", ".git",
                                                  "dist", "build"))
            else:
                shutil.copy2(item, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return staging


BAT_TEMPLATE = """@echo off
setlocal
set PID=%1
set SHA=%2
cd /d "%~dp0"
echo Waiting for BillBook to close...
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto waitloop )
echo Applying update...
robocopy "update_staging" "." /E /XD billbook_data update_staging __pycache__ .git dist build /XF apply_update.bat update_log.txt > update_log.txt 2>&1
echo Rebuilding BillBook.exe (this takes a few minutes)...
python -m pip install --quiet --upgrade customtkinter pyinstaller reportlab pywin32 pymupdf pillow >> update_log.txt 2>&1
pyinstaller --noconfirm --onefile --windowed --name BillBook --hidden-import fitz --hidden-import pymupdf --hidden-import PIL.ImageWin main.py >> update_log.txt 2>&1
if errorlevel 1 (
  echo UPDATE FAILED - your old version was NOT touched. > update_error.txt
  echo See update_log.txt for details. >> update_error.txt
  start "" notepad update_log.txt
  rmdir /S /Q update_staging
  del apply_update.bat
  exit /b 1
)
if exist "dist\\BillBook.exe" copy /Y "dist\\BillBook.exe" "BillBook.exe" >nul 2>&1
echo %SHA% > version.txt
rmdir /S /Q update_staging
echo Update complete - restarting BillBook...
if exist "BillBook.exe" ( start "" "BillBook.exe" ) else ( start "" python main.py )
del apply_update.bat
"""


def write_apply_bat() -> Path:
    bat = app_dir() / "apply_update.bat"
    bat.write_text(BAT_TEMPLATE, encoding="utf-8")
    return bat


def launch_apply_and_quit(bat: Path, pid: int, sha: str, quit_app) -> None:
    """Start apply_update.bat detached, then quit the app (which lets the
    bat replace files and rebuild once this process is gone)."""
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat), str(pid), sha],
            cwd=str(app_dir()),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        subprocess.Popen(["cmd", "/c", str(bat), str(pid), sha],
                         cwd=str(app_dir()))
    quit_app()
