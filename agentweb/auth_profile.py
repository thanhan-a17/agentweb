"""Persistent browser auth profiles for AgentWeb.

Manages Camoufox browser instances with persistent user data directories
so users can sign into services (Facebook, Instagram, X, Reddit, etc.)
once and reuse those sessions for agent-driven data gathering.
"""

from __future__ import annotations

import atexit
import errno
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stealth import stealth_script_for_level

# ── Paths ───────────────────────────────────────────────────────────────

AGENTWEB_CONFIG = Path.home() / ".config" / "agentweb"
PROFILES_DIR = AGENTWEB_CONFIG / "auth-profiles"

# ── Fingerprint ─────────────────────────────────────────────────────────

DEFAULT_FINGERPRINT: dict[str, Any] = {
    "viewport_width": 1280,
    "viewport_height": 800,
    "locale": "en-US",
    "geolocation_latitude": 40.7128,
    "geolocation_longitude": -74.0060,
    "timezone_id": "America/New_York",
    "humanize": True,
}

# ── Lock tracking ───────────────────────────────────────────────────────

_LOCK_FDS: dict[str, int] = {}
"""Tracks open lock file descriptors keyed by profile name for cleanup."""



def _profile_dir(name: str) -> Path:
    return PROFILES_DIR / name


def _meta_path(name: str) -> Path:
    return _profile_dir(name) / "meta.json"


def _user_data_dir(name: str) -> Path:
    return _profile_dir(name) / "browser-data"


# ── Data ────────────────────────────────────────────────────────────────


@dataclass
class BrowserProfile:
    """Represents one persistent auth browser profile."""

    name: str
    pid: int | None = None
    created_at: str = ""
    last_used: str = ""
    services: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Profile CRUD ────────────────────────────────────────────────────────


def _ensure_profile_dir(name: str) -> None:
    """Create directory structure for a profile if it doesn't exist."""
    udd = _user_data_dir(name)
    udd.mkdir(parents=True, exist_ok=True)


def _read_meta(name: str) -> dict[str, Any]:
    path = _meta_path(name)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_meta(name: str, data: dict[str, Any]) -> None:
    path = _meta_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── File locking ─────────────────────────────────────────────────────────


def _lock_path(name: str) -> Path:
    return _profile_dir(name) / ".lock"


def _acquire_lock(name: str) -> None:
    """Acquire an exclusive file lock on the profile directory.

    Raises PermissionError if another process holds the lock.
    The lock is auto-released when the process exits or the FD is closed.
    """
    lock_file = _lock_path(name)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (
            errno.EAGAIN,
            errno.EWOULDBLOCK,
        ):
            raise PermissionError(
                f"Profile '{name}' is locked by another process. "
                "Close the other browser session first."
            ) from exc
        raise
    _LOCK_FDS[name] = fd


def _release_lock(name: str) -> None:
    """Release the lock on a profile directory."""
    fd = _LOCK_FDS.pop(name, None)
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


def _release_all_locks() -> None:
    """Release all held locks (called atexit or on error)."""
    for name in list(_LOCK_FDS):
        _release_lock(name)


atexit.register(_release_all_locks)


# ── Fingerprint ──────────────────────────────────────────────────────────


def _current_fingerprint() -> dict[str, Any]:
    """Return the current browser fingerprint settings."""
    return dict(DEFAULT_FINGERPRINT)


def _verify_fingerprint(meta: dict[str, Any], profile_name: str) -> list[str]:
    """Compare stored fingerprint with current config. Return warnings list."""
    stored = meta.get("fingerprint")
    if not stored:
        return []  # First open — no prior fingerprint to compare
    current = _current_fingerprint()
    diffs: list[str] = []
    for key, expected in current.items():
        actual = stored.get(key)
        if actual is not None and actual != expected:
            diffs.append(f"{key}: was {actual!r}, now {expected!r}")
    return diffs


def list_profiles() -> list[BrowserProfile]:
    """List all existing auth browser profiles."""
    if not PROFILES_DIR.exists():
        return []
    profiles: list[BrowserProfile] = []
    for entry in sorted(PROFILES_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            meta = _read_meta(entry.name)
            pid = meta.get("pid")
            if pid is not None and not _pid_alive(pid):
                pid = None
                meta["pid"] = None
                _write_meta(entry.name, meta)
            p = BrowserProfile(
                name=entry.name,
                pid=pid,
                created_at=meta.get("created_at", ""),
                last_used=meta.get("last_used", ""),
                services=meta.get("services", []),
            )
            profiles.append(p)
    return profiles


def get_profile(name: str) -> BrowserProfile | None:
    """Get a profile by name, or None if it doesn't exist."""
    if not _profile_dir(name).exists():
        return None
    meta = _read_meta(name)
    pid = meta.get("pid")
    if pid is not None and not _pid_alive(pid):
        pid = None
    return BrowserProfile(
        name=name,
        pid=pid,
        created_at=meta.get("created_at", ""),
        last_used=meta.get("last_used", ""),
        services=meta.get("services", []),
    )


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ── Browser lifecycle ───────────────────────────────────────────────────


def _find_user_data_dirs() -> dict[str, Path]:
    """Discover Camoufox/Playwright profile directories on disk."""
    dirs: dict[str, Path] = {}
    if PROFILES_DIR.exists():
        for entry in PROFILES_DIR.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                browser_data = entry / "browser-data"
                if browser_data.exists():
                    dirs[entry.name] = browser_data
    return dirs


def _detect_viewport() -> dict[str, int]:
    """Detect usable screen area and return a viewport sized to fit comfortably.

    Returns {'width': W, 'height': H} at ~88% of the screen's work area
    so the browser window fits without overlapping docks/menus.
    Falls back to 1280×800 if detection fails.
    """
    try:
        import pyautogui
        w, h = pyautogui.size()
    except Exception:
        try:
            import tkinter
            r = tkinter.Tk()
            w, h = r.winfo_screenwidth(), r.winfo_screenheight()
            r.destroy()
        except Exception:
            return {"width": 1280, "height": 800}
    # macOS menu bar ~25px, dock can add width — leave 12% margin
    return {"width": int(w * 0.88), "height": int(h * 0.88)}


CAMOUFOX_SCRIPT = r"""
import sys
import json
import signal
import os

try:
    from camoufox.sync_api import Camoufox
except ImportError:
    print(json.dumps({"error": "camoufox not installed—run: uv add camoufox"}))
    sys.exit(1)

profile_name = sys.argv[1]
user_data_dir = sys.argv[2]
timeout_sec = int(sys.argv[3]) if len(sys.argv) > 3 else 0
viewport_json = sys.argv[4] if len(sys.argv) > 4 else '{{"width": 1280, "height": 800}}'
viewport = json.loads(viewport_json)
_session_saved = False

stealth_level = sys.argv[5] if len(sys.argv) > 5 else "off"
stealth_js = ""
stealth_extra_args = []
if stealth_level != "off":
    try:
        from agentweb.stealth import stealth_script_for_level
        stealth_js = stealth_script_for_level(stealth_level)
    except Exception:
        pass
    if stealth_js:
        stealth_extra_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-automation-extension",
            "--no-first-run",
        ]

def _handle_sigterm(signum, frame):
    global _session_saved
    _session_saved = True
    # Let the with-block exit cleanly so cookies/session flush to disk
    os._exit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)

try:
    with Camoufox(
        headless=False,
        persistent_context=True,
        user_data_dir=user_data_dir,
        humanize=True,
        viewport=viewport,
        locale="en-US",
        geolocation={"latitude": 40.7128, "longitude": -74.0060},
        timezone_id="America/New_York",
        args=stealth_extra_args if stealth_extra_args else None,
    ) as browser:
        # Use the existing page from persistent context — avoid creating
        # duplicate tabs/windows. Explicitly set viewport on whichever
        # page we end up using so content renders at the right size.
        pages = browser.pages
        page = pages[0] if pages else browser.new_page()
        if stealth_js:
            page.add_init_script(stealth_js)
        page.set_viewport_size(viewport)
        page.goto("about:blank")
        # Keep the browser alive. The persistent_context ensures
        # all cookies/sessions/localStorage are flushed to disk.
        import time as _time
        while True:
            _time.sleep(1)
except KeyboardInterrupt:
    pass
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
    sys.exit(1)
finally:
    # Flush cookies to disk before exit
    import time as _time
    _time.sleep(0.5)
    if not _session_saved:
        _session_saved = True
"""


def open_browser(
    profile_name: str = "default",
    *,
    services: list[str] | None = None,
    stealth_level: str = "off",
) -> dict[str, Any]:
    """Open a persistent Camoufox browser for the user to sign into services.

    The browser launches non-headless with a persistent user data directory.
    The user sees the browser window and can sign into any services they need.
    The profile is re-used across sessions — re-open restores previous logins.

    A file lock prevents concurrent processes from corrupting the profile.
    The browser fingerprint is stored on first open and verified on re-open
    to detect config changes that might trigger security alerts.

    Returns meta dict with profile info.
    """
    _ensure_profile_dir(profile_name)
    udd = _user_data_dir(profile_name)
    meta = _read_meta(profile_name)

    # ── Acquire file lock ──────────────────────────────────────────
    try:
        _acquire_lock(profile_name)
    except PermissionError as exc:
        return {
            "status": "locked",
            "profile": profile_name,
            "message": str(exc),
        }

    if meta.get("pid") and _pid_alive(meta["pid"]):
        _release_lock(profile_name)
        return {
            "status": "already_running",
            "profile": profile_name,
            "pid": meta["pid"],
            "message": f"Browser for '{profile_name}' is already running (PID {meta['pid']}).",
        }

    # ── Check Camoufox availability ────────────────────────────────
    try:
        import camoufox  # noqa: F401
    except ImportError:
        _release_lock(profile_name)
        return {
            "status": "error",
            "profile": profile_name,
            "message": "Camoufox is not installed. Run: uv add camoufox",
        }

    # ── Fingerprint check ──────────────────────────────────────────
    fingerprint_warnings = _verify_fingerprint(meta, profile_name)

    viewport = _detect_viewport()
    proc = subprocess.Popen(
        [
            sys.executable or "python3",
            "-c",
            CAMOUFOX_SCRIPT,
            profile_name,
            str(udd),
            str(3600),  # default 1-hour timeout safety net
            json.dumps(viewport),
            stealth_level,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )

    # Wait a moment for the browser to start
    time.sleep(3)

    pid = proc.pid
    if pid and _pid_alive(pid):
        now = _now()
        meta["pid"] = pid
        meta["created_at"] = meta.get("created_at", now)
        meta["last_used"] = now
        if services:
            existing = set(meta.get("services", []))
            existing.update(services)
            meta["services"] = sorted(existing)
        # Store fingerprint on first open
        if "fingerprint" not in meta:
            meta["fingerprint"] = _current_fingerprint()
        _write_meta(profile_name, meta)

        message_parts = [
            f"✓ Browser opened for profile '{profile_name}' (PID {pid}).",
            "",
            "A Camoufox window should appear. Sign into your services now.",
            "All cookies, sessions, and local storage are saved to disk automatically.",
            "",
            "┌─ What to do ─────────────────────────────────────────────┐",
            "│  • Sign into Facebook, Instagram, X, Reddit, etc.       │",
            "│  • Close the browser window when you're done signing in │",
            "│  • Your sessions persist — no need to re-sign later     │",
            "└─────────────────────────────────────────────────────────┘",
            "",
            "  agentweb auth close          — stop the browser",
            "  agentweb fetch --profile ... — fetch authenticated pages",
            "  agentweb research --profile  — research with logged-in access",
        ]
        if fingerprint_warnings:
            message_parts.extend([
                "",
                "⚠  Fingerprint changes detected (may trigger security alerts):",
                *[f"   • {w}" for w in fingerprint_warnings],
            ])

        result = {
            "status": "started",
            "profile": profile_name,
            "pid": pid,
            "user_data_dir": str(udd),
            "message": "\n".join(message_parts),
        }
        if fingerprint_warnings:
            result["fingerprint_warnings"] = fingerprint_warnings
        return result

    # Read any stderr to understand failure
    _release_lock(profile_name)
    _stderr = proc.stderr.read() if proc.stderr else ""
    return {
        "status": "error",
        "profile": profile_name,
        "message": f"Browser failed to start: {_stderr[:500] or 'unknown error'}",
    }


def close_browser(profile_name: str = "default") -> dict[str, Any]:
    """Close the browser for a profile and save session to disk."""
    meta = _read_meta(profile_name)
    pid = meta.get("pid")
    if pid is None:
        return {
            "status": "not_running",
            "profile": profile_name,
            "message": f"No browser running for '{profile_name}'.",
        }
    if not _pid_alive(pid):
        meta["pid"] = None
        _write_meta(profile_name, meta)
        _release_lock(profile_name)
        return {
            "status": "already_closed",
            "profile": profile_name,
            "message": f"Browser for '{profile_name}' was already closed. Sessions were saved to disk.",
        }

    try:
        os.kill(pid, signal.SIGTERM)
        # Give it a moment to shut down gracefully and flush cookies to disk
        for _ in range(10):
            if not _pid_alive(pid):
                break
            time.sleep(0.5)
        else:
            os.kill(pid, signal.SIGKILL)
    except OSError:
        pass

    meta["pid"] = None
    meta["last_used"] = _now()
    _write_meta(profile_name, meta)
    _release_lock(profile_name)
    return {
        "status": "closed",
        "profile": profile_name,
        "message": (
            f"✓ Browser for '{profile_name}' closed. "
            "All sessions (cookies, tokens, local storage) saved to disk. "
            "Your logins will be restored when you reopen this profile."
        ),
    }


def delete_profile(profile_name: str) -> dict[str, Any]:
    """Delete a profile and all its data."""
    close_browser(profile_name)
    _release_lock(profile_name)
    profile_dir = _profile_dir(profile_name)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
        return {
            "status": "deleted",
            "profile": profile_name,
            "message": f"Profile '{profile_name}' and all its data deleted. All sessions erased.",
        }
    return {
        "status": "not_found",
        "profile": profile_name,
        "message": f"Profile '{profile_name}' does not exist.",
    }


def browser_status(profile_name: str = "default") -> dict[str, Any]:
    """Check the status of a browser profile."""
    profile_dir = _profile_dir(profile_name)
    if not profile_dir.exists():
        return {
            "status": "no_profile",
            "profile": profile_name,
            "message": f"Profile '{profile_name}' does not exist. Use 'agentweb auth open --profile {profile_name}' to create it.",
        }

    meta = _read_meta(profile_name)
    pid = meta.get("pid")
    alive = pid is not None and _pid_alive(pid)

    if alive:
        return {
            "status": "running",
            "profile": profile_name,
            "pid": pid,
            "created_at": meta.get("created_at", ""),
            "last_used": meta.get("last_used", ""),
            "services": meta.get("services", []),
            "user_data_dir": str(_user_data_dir(profile_name)),
            "message": f"Browser for '{profile_name}' is running (PID {pid}).",
        }
    else:
        if pid is not None:
            meta["pid"] = None
            _write_meta(profile_name, meta)
        return {
            "status": "stopped",
            "profile": profile_name,
            "created_at": meta.get("created_at", ""),
            "last_used": meta.get("last_used", ""),
            "services": meta.get("services", []),
            "user_data_dir": str(_user_data_dir(profile_name)),
            "message": (
                f"✓ Profile '{profile_name}' — browser closed, sessions saved. "
                f"Data directory has {_dir_size(_user_data_dir(profile_name))} of stored sessions. "
                "Use 'agentweb auth open' to launch the browser again — you'll still be logged in."
            ),
        }


def _dir_size(path: Path) -> str:
    """Return a human-readable size for a directory."""
    if not path.exists():
        return "0 B"
    total = sum(
        f.stat().st_size for f in path.rglob("*") if f.is_file()
    )
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024:
            return f"{total:.0f} {unit}"
        total /= 1024
    return f"{total:.1f} GB"


# ── Fetch integration ───────────────────────────────────────────────────


def _read_cookies_sqlite(udd: Path) -> list[dict[str, str | int | bool]] | None:
    """Read cookies from Firefox's on-disk cookies.sqlite.

    Firefox writes cookies here during normal (non-headless) browsing.
    Playwright's headless mode does NOT load from this file automatically,
    so we read it directly and inject cookies into the headless context.
    Returns None if the file doesn't exist or can't be read.
    """
    cookie_db = udd / "cookies.sqlite"
    if not cookie_db.exists():
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite "
            "FROM moz_cookies"
        ).fetchall()
        conn.close()

        # Map Firefox integer sameSite to Playwright string values
        _SAMESITE_MAP: dict[int, str] = {0: "None", 1: "Lax", 2: "Strict"}

        cookies: list[dict[str, str | int | bool]] = []
        for row in rows:
            # Firefox stores host with leading dot for domain cookies
            # (e.g., ".httpbin.org"), but Playwright expects NO leading dot.
            host = str(row["host"] or "")
            if host.startswith("."):
                host = host[1:]
            cookies.append({
                "name": row["name"],
                "value": row["value"],
                "domain": host,
                "path": row["path"],
                "expires": row["expiry"],
                "secure": bool(row["isSecure"]),
                "httpOnly": bool(row["isHttpOnly"]),
                "sameSite": _SAMESITE_MAP.get(row["sameSite"], "None"),
            })
        return cookies
    except Exception:
        return None


def extract_cookies(profile_name: str = "default") -> dict[str, str]:
    """Extract cookies from a persistent browser profile.

    First tries Camoufox headless context (captures cookies set this session),
    then falls back to reading Firefox's cookies.sqlite directly
    (captures cookies set by a previous non-headless login session).

    Returns a flat dict suitable for passing as a Cookie header.
    Returns empty dict if the profile doesn't exist or has no cookies.
    """
    udd = _user_data_dir(profile_name)
    if not udd.exists():
        return {}

    cookies: dict[str, str] = {}

    # Pre-read SQLite cookies BEFORE launching headless Camoufox,
    # because Camoufox headless mode clears cookies.sqlite on startup.
    sqlite_cookies = _read_cookies_sqlite(udd)
    if sqlite_cookies:
        for c in sqlite_cookies:
            name = str(c.get("name", ""))
            value = str(c.get("value", ""))
            if name and value:
                cookies[name] = value

    # If SQLite already has cookies, return them immediately.
    # Avoid launching headless Camoufox because it clears cookies.sqlite,
    # which would break subsequent fetch_with_profile calls.
    if cookies:
        return cookies

    # Method 1: Launch headless Camoufox to get in-memory cookies
    # (cookies set during the current Camoufox session via JS/redirects).
    try:
        from camoufox.sync_api import Camoufox

        with Camoufox(
            headless=True,
            persistent_context=True,
            user_data_dir=str(udd),
            humanize=False,
            viewport={"width": 800, "height": 600},
        ) as context:
            for c in context.cookies():
                if c.get("name") and c.get("value"):
                    cookies[str(c["name"])] = str(c["value"])
            return cookies
    except Exception:
        pass

    return cookies


def fetch_with_profile(
    url: str,
    profile_name: str = "default",
    *,
    timeout: int = 30,
    stealth_level: str = "off",
) -> str | None:
    """Fetch a URL using an authenticated browser profile.

    Launches a headless Camoufox with the profile's persistent context.
    Injects cookies from the on-disk Firefox cookies.sqlite so that
    sessions from a prior non-headless login (via ``auth open``) are
    available without triggering new login prompts.

    Supports stealth via ``stealth_level`` (off/standard/aggressive),
    same as the ``fetch`` / ``research`` / ``crawl`` commands.

    Returns the page text on success, or None on failure.
    """
    udd = _user_data_dir(profile_name)
    if not udd.exists():
        return None

    # Pre-read cookies from on-disk SQLite (set by a real Firefox login)
    sqlite_cookies = _read_cookies_sqlite(udd)

    script = r"""
import sys, json
try:
    from camoufox.sync_api import Camoufox
except ImportError:
    sys.exit(2)

url = sys.argv[1]
udd = sys.argv[2]
timeout_ms = int(sys.argv[3]) * 1000
cookies_json = sys.argv[4] if len(sys.argv) > 4 else "[]"
stealth_level = sys.argv[5] if len(sys.argv) > 5 else "off"

stealth_js = ""
stealth_extra_args = None
if stealth_level != "off":
    try:
        from agentweb.stealth import stealth_script_for_level
        stealth_js = stealth_script_for_level(stealth_level)
    except Exception:
        pass
    if stealth_js:
        stealth_extra_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-automation-extension",
            "--no-first-run",
        ]

try:
    with Camoufox(
        headless=True,
        persistent_context=True,
        user_data_dir=udd,
        humanize=True,
        viewport={"width": 1280, "height": 800},
        args=stealth_extra_args,
    ) as context:
        # Inject cookies from on-disk SQLite so headless mode
        # has the same sessions as the non-headless login browser.
        persisted = json.loads(cookies_json)
        if persisted:
            context.add_cookies(persisted)

        page = context.new_page()
        if stealth_js:
            page.add_init_script(stealth_js)
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        title = page.title()
        text = page.locator("body").inner_text(timeout=5000)
        cookies = {c["name"]: c["value"] for c in context.cookies()}
        print(json.dumps({
            "title": title,
            "text": text[:50000],
            "cookies": cookies,
        }))
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
    sys.exit(1)
"""

    try:
        proc = subprocess.run(
            [sys.executable or "python3", "-c", script, url, str(udd), str(timeout), json.dumps(sqlite_cookies or []), stealth_level],
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            if "text" in data:
                return data["text"]
            if "error" in data:
                return None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None
