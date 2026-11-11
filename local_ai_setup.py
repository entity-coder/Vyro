"""
Vyro — one-click local AI download (Ollama + Qwen3-4B, 2026-11-10).

Pure logic, no GUI imports, so it can be tested headless. The AI
Insights Assistant tab (ai_features.py) calls run_setup() in a
background thread and shows progress through the callbacks.

Flow: detect Ollama -> download the installer (only if missing) ->
silent install -> pull the model -> verify -> ready. The assistant
keeps working with the Gemini fallback (or its "not available"
message) until local AI is verified ready; nothing is half-configured.

Verified facts (2026-11-10, not guesses):
- Download URL https://ollama.com/download/OllamaSetup.exe 307-redirects
  to github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe
  (currently v0.40.16). urllib follows the redirect.
- The installer is Inno Setup, NOT NSIS — so the "/S" flag does not
  apply. Ollama's own updater (app/updater/updater_windows.go in the
  ollama repo) runs it with /VERYSILENT /SUPPRESSMSGBOXES (+ /NORESTART
  here, so a reboot never interrupts billing). The installer is
  per-user (%LOCALAPPDATA%\\Programs\\Ollama) — no admin rights needed.
- Model size ~2.5 GB; the whole download is ~3 GB with the installer,
  so setup checks for 4 GB free first.

Wording rule (2026-11-10): no mention of any personal/family shop in
user-facing strings — generic "wholesale/kirana shop" only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_MODEL = "qwen3:4b"
OLLAMA_API_URL = "http://localhost:11434"
INSTALLER_NAME = "OllamaSetup.exe"
# Installer + model + working room.
REQUIRED_FREE_BYTES = 4 * 1024 ** 3
# Inno Setup silent flags (see module docstring for the source).
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
SERVER_WAIT_SECONDS = 30

# States: "missing" (no Ollama), "ollama_only" (Ollama, no model),
# "ready" (Ollama + model).


class SetupError(Exception):
    """A setup step failed; str() is the plain message for the user."""


class CancelledError(Exception):
    """The user cancelled; nothing was changed."""


def find_ollama(which=None, local_app_data=None):
    """Path to the ollama program, or None. Checks PATH first, then
    the default Windows install folder."""
    which = which or shutil.which
    found = which("ollama")
    if found:
        return found
    base = local_app_data
    if base is None:
        base = os.environ.get("LOCALAPPDATA", "")
    if base:
        candidate = os.path.join(base, "Programs", "Ollama",
                                 "ollama.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def api_models(url, timeout=2):
    """Model names from a running Ollama server; [] when it is not
    reachable. Never raises."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _server_up(url, timeout=2):
    """True when the Ollama server answers at all (even with no
    models). Never raises."""
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True
    except Exception:
        return False


def wait_for_server(url, timeout=SERVER_WAIT_SECONDS, interval=2,
                    server_up=None, sleep=None):
    """Poll until the Ollama server answers (it starts with the
    installer). True when up, False when the wait runs out."""
    server_up = server_up or _server_up
    sleep = sleep or time.sleep
    waited = 0
    while waited <= timeout:
        if server_up(url):
            return True
        sleep(interval)
        waited += interval
    return False


def detect_state(ollama_path, models, model=OLLAMA_MODEL):
    """Setup state from a detected program path + installed models."""
    if not ollama_path:
        return "missing"
    if model in (models or []):
        return "ready"
    return "ollama_only"


def current_state(model=OLLAMA_MODEL, url=OLLAMA_API_URL, timeout=1):
    """Live state for the button label (quick localhost check)."""
    return detect_state(find_ollama(), api_models(url, timeout), model)


def button_label(state):
    """'Download local AI' until Ollama + model are both present,
    then 'Update local AI' (re-pulls the model for the latest)."""
    return "Update local AI" if state == "ready" else "Download local AI"


def confirm_text(state, model=OLLAMA_MODEL):
    """Plain confirmation shown before anything downloads."""
    if state == "ready":
        return (f"Update local AI?\n\nVyro will re-download "
                f"'{model}' to get the latest version "
                f"(about 2.5 GB if a new version is available — quick "
                f"if you already have it). Needs internet. The assistant "
                f"keeps working while it downloads.")
    return (f"Download local AI?\n\nVyro will download and install:\n"
            f"- Ollama (about 300 MB) — runs the AI on this PC\n"
            f"- The '{model}' model (about 2.5 GB)\n\n"
            f"About 3 GB in total. Needs internet and a few minutes on "
            f"a fast connection (longer on a slow one). The install is "
            f"per-user, so no admin rights are needed. You can cancel "
            f"any time before the install starts.")


def manual_steps_text(model=OLLAMA_MODEL):
    """Fallback when one-click setup cannot run: the manual path."""
    return (f"Or install it yourself: download Ollama from "
            f"ollama.com, run the installer, then run:\n"
            f"ollama pull {model}")


def has_enough_disk(free_bytes, required=REQUIRED_FREE_BYTES):
    """True when `free_bytes` covers the download + working room."""
    return free_bytes >= required


def parse_pull_line(line):
    """One 'ollama pull' output line -> (status text, fraction|None).
    Progress lines carry a percent; 'success' means done."""
    text = (line or "").strip()
    if not text:
        return ("", None)
    if "success" in text.lower():
        return (text, 1.0)
    m = re.search(r"(\d+)%", text)
    if m:
        return (text, int(m.group(1)) / 100.0)
    return (text, None)


def model_in_list(output, model=OLLAMA_MODEL):
    """True when `ollama list` output has the model (first column,
    header line skipped)."""
    for line in (output or "").splitlines():
        parts = line.split()
        if parts and parts[0] == model:
            return True
    return False


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def download_installer(url, dest, on_progress, is_cancelled,
                       opener=None, chunk=256 * 1024):
    """Download the installer to `dest` (follows redirects).
    on_progress(fraction|None) per chunk; raises CancelledError
    (partial file removed) or SetupError with a plain message."""
    opener = opener or urllib.request.urlopen
    try:
        with opener(url, timeout=30) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    if is_cancelled():
                        raise CancelledError()
                    data = resp.read(chunk)
                    if not data:
                        break
                    f.write(data)
                    downloaded += len(data)
                    on_progress(downloaded / total if total else None)
        if os.path.getsize(dest) <= 0:
            raise SetupError("The installer download came back empty — "
                             "check your internet and try again.")
    except CancelledError:
        _remove_quietly(dest)
        raise
    except SetupError:
        _remove_quietly(dest)
        raise
    except urllib.error.URLError as e:
        _remove_quietly(dest)
        raise SetupError("Could not download the installer "
                         f"({e.reason or e}) — check your internet and "
                         "try again.")
    except OSError as e:
        _remove_quietly(dest)
        raise SetupError(f"Could not save the installer: {e}")


def run_installer(path, run=None):
    """Silent install (Windows only — see module docstring). Non-zero
    exit raises SetupError."""
    if not sys.platform.startswith("win"):
        raise SetupError("Automatic install works on Windows only — "
                         "install Ollama yourself from ollama.com, "
                         "then tap the button again.")
    run = run or subprocess.run
    res = run([path] + INSTALLER_ARGS)
    if res.returncode != 0:
        raise SetupError("Ollama install failed "
                         f"(installer exited with code "
                         f"{res.returncode}) — try running the installer "
                         "yourself, or tap the button to try again.")


def pull_model(ollama, model, on_line, is_cancelled, popen=None):
    """Run 'ollama pull <model>', streaming one status line at a
    time. Cancel terminates the download. Non-zero exit raises
    SetupError."""
    popen = popen or subprocess.Popen
    proc = popen([ollama, "pull", model], stdout=subprocess.DEVNULL,
                 stderr=subprocess.PIPE, text=True)
    try:
        for line in proc.stderr:
            if is_cancelled():
                proc.terminate()
                raise CancelledError()
            on_line(line)
    finally:
        if proc.poll() is None:
            proc.wait()
    if proc.returncode != 0:
        raise SetupError("Model download failed (Ollama exited with "
                         f"code {proc.returncode}) — check your internet "
                         "and tap the button to try again.")


def verify_model(ollama, model, url, run=None, api=None):
    """True when the model is installed: 'ollama list' first, the
    server's model list as a fallback. Never raises."""
    try:
        run = run or subprocess.run
        res = run([ollama, "list"], capture_output=True, text=True,
                  timeout=15)
        if res.returncode == 0 and model_in_list(res.stdout, model):
            return True
    except Exception:
        pass
    return model in (api or api_models)(url)


def run_setup(model, url, on_status, on_progress, is_cancelled,
              find=None, api=None, disk_free=None, download=None,
              install=None, pull=None, verify=None, wait=None,
              tempdir=None):
    """One-click setup in a background thread. Returns
    {"ok": bool, "cancelled": bool, "error": str}. Never raises, never
    touches the database (the caller flips the provider to local on
    success, on the GUI thread). All slow steps are injectable so tests
    can fake them."""
    find = find or find_ollama
    api = api or api_models
    disk_free = disk_free or (lambda p: shutil.disk_usage(p).free)
    download = download or download_installer
    install = install or run_installer
    pull = pull or pull_model
    verify = verify or verify_model
    wait = wait or wait_for_server
    tempdir = tempdir or tempfile.gettempdir
    try:
        on_status("Checking what is already installed…")
        ollama = find()
        state = detect_state(ollama, api(url) if ollama else [], model)
        free = disk_free(tempdir())
        if not has_enough_disk(free):
            raise SetupError("Not enough free space — the download "
                             "needs about 4 GB free. Free up space "
                             "and try again.")
        if ollama is None:
            on_status("Downloading Ollama installer (about 300 MB)…")
            dest = os.path.join(tempdir(), INSTALLER_NAME)
            download(OLLAMA_DOWNLOAD_URL, dest, on_progress,
                     is_cancelled)
            on_status("Installing Ollama (per-user, no admin needed)…")
            on_progress(None)
            try:
                install(dest)
            finally:
                _remove_quietly(dest)
            ollama = find()
            if ollama is None:
                raise SetupError("Ollama installed but the program was "
                                 "not found — open Ollama once from the "
                                 "Start menu, then tap the button again.")
            on_status("Waiting for Ollama to start…")
            if not wait(url):
                raise SetupError("Ollama installed but its server did "
                                 "not start — open Ollama from the Start "
                                 "menu and tap the button again.")
        if state == "ready":
            on_status(f"Updating the {model} model to the latest "
                      "version…")
        else:
            on_status(f"Downloading the {model} model (about 2.5 GB) — "
                      "this is the long step…")

        def _line(line):
            text, frac = parse_pull_line(line)
            if text:
                on_status(text)
            if frac is not None:
                on_progress(frac)

        pull(ollama, model, _line, is_cancelled)
        on_status("Checking the model is ready…")
        if not verify(ollama, model, url):
            raise SetupError(f"The model '{model}' did not appear after "
                             "the download — check your internet and tap "
                             "the button to try again.")
        on_progress(1.0)
        return {"ok": True, "cancelled": False, "error": ""}
    except CancelledError:
        return {"ok": False, "cancelled": True,
                "error": "Download cancelled — nothing was changed. "
                         "Tap the button to try again."}
    except SetupError as e:
        return {"ok": False, "cancelled": False, "error": str(e)}
