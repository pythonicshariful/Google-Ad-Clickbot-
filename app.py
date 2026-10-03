"""
app.py — PyWebView Desktop App Launcher
Wraps the clickbot in a beautiful desktop UI window.
The HTML/CSS/JS frontend communicates with this Python bridge.
"""

import json
import logging
import os
import sys
import threading
import time
import random
import queue
from datetime import datetime

import webview

# ── Add project root to path ──────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Import bot internals ───────────────────────────────────────────────────────
sys.path.insert(0, BASE_DIR)
IMPORT_ERROR = None
try:
    from clickbot import (
        load_config,
        create_driver,
        search_google,
        detect_ads,
        click_ad,
        build_proxy_string,
        run_cycle,
        write_last_run_info,
        append_session_summary,
        close_driver_safely,
    )
except Exception as _ie:
    IMPORT_ERROR = str(_ie)
    # Provide stubs so the rest of app.py doesn't crash on definition
    def load_config(path):    return json.load(open(path))
    def build_proxy_string(c): return ""
    def create_driver(*a, **kw): raise RuntimeError(IMPORT_ERROR)
    def search_google(*a, **kw): return False
    def detect_ads(*a, **kw):   return []
    def click_ad(*a, **kw):     return False
    def run_cycle(config, logger, n, use_proxy=True): raise RuntimeError(IMPORT_ERROR)
    def write_last_run_info(*a, **kw): return os.path.join(BASE_DIR, "last_run_info.txt")
    def append_session_summary(config, lines): return os.path.join(BASE_DIR, "session_summary.txt")
    def close_driver_safely(d, logger=None): pass

# ── Globals ────────────────────────────────────────────────────────────────────
CONFIG_PATH   = os.path.join(BASE_DIR, "config.json")
LOG_QUEUE     = queue.Queue()          # thread-safe log buffer → UI
bot_thread    = None
bot_running   = False
stop_event    = threading.Event()

stats = {
    "total_clicks":   0,
    "cycles_done":    0,
    "ads_found":      0,
    "current_keyword": "",
    "current_ip":     "—",
    "status":         "stopped",       # "running" | "stopped" | "error"
    "next_cycle_secs": 0,
}

activity_log = []   # list of recent cycle summaries


# ── Logging bridge ────────────────────────────────────────────────────────────

class QueueHandler(logging.Handler):
    """Push log records into the thread-safe queue for the UI to poll."""
    def emit(self, record):
        msg = self.format(record)
        LOG_QUEUE.put({"level": record.levelname, "message": msg})


def setup_logger():
    logger = logging.getLogger("clickbot_ui")
    logger.setLevel(logging.DEBUG)
    # File handler
    fh = logging.FileHandler(os.path.join(BASE_DIR, "clickbot.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    # Queue handler → UI
    qh = QueueHandler()
    qh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(qh)
    return logger


logger = setup_logger()


# ── Bot worker thread ─────────────────────────────────────────────────────────

def bot_worker(use_proxy=True):
    global stats, activity_log, bot_running

    config   = load_config(CONFIG_PATH)
    interval = config["search"].get("cycle_interval_minutes", 20) * 60
    keywords = config["search"].get("keywords", []) or []

    stats["status"] = "running"
    logger.info("Bot started.")

    cycle_number = 0
    total_clicks = 0

    # Init the persistent copyable files (same as clickbot CLI main())
    try:
        append_session_summary(config, [])   # writes header on first run
        write_last_run_info(
            config, 0, 0,
            extra="Bot started (UI mode) — waiting for first cycle.",
        )
    except Exception:
        pass

    # Also show banner paths in the log so users can copy from Logs tab text
    try:
        _cfg = load_config(CONFIG_PATH)
        log_p = (_cfg.get("logging") or {}).get("log_file", "clickbot.log")
    except Exception:
        log_p = "clickbot.log"
    log_file_p = os.path.join(BASE_DIR, log_p) if not os.path.isabs(log_p) else log_p
    sum_file_p = os.path.join(BASE_DIR, "session_summary.txt")
    lr_file_p  = os.path.join(BASE_DIR, "last_run_info.txt")
    logger.info(f"Copyable paths  ->  Log: {log_file_p}")
    logger.info(f"Copyable paths  ->  Summary: {sum_file_p}")
    logger.info(f"Copyable paths  ->  Last run: {lr_file_p}")

    # Get proxy IP once at startup (for display only)
    try:
        import requests
        proxy_str = build_proxy_string(config["proxy"]) if use_proxy else None
        proxies   = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"} if proxy_str else {}
        ip_data   = requests.get("https://api.ipify.org?format=json", proxies=proxies, timeout=10).json()
        stats["current_ip"] = ip_data.get("ip", "—")
    except Exception:
        stats["current_ip"] = "—"

    try:
        while not stop_event.is_set():
            cycle_number += 1
            config = load_config(CONFIG_PATH)
            interval = config["search"].get("cycle_interval_minutes", 20) * 60
            keywords = config["search"].get("keywords", []) or []
            stats["cycles_done"] = cycle_number

            # Show a "current keyword" hint = first keyword of current cycle set
            shuffled_preview = list(keywords)
            random.shuffle(shuffled_preview)
            first_kw = shuffled_preview[0] if shuffled_preview else ""
            stats["current_keyword"] = first_kw

            max_attempts = min(
                int(config["search"].get("max_keyword_attempts_per_cycle", len(keywords))),
                len(keywords),
            )
            logger.info(
                f"=== CYCLE #{cycle_number} START | "
                f"attempts up to {max_attempts}, browser stays open all cycle ==="
            )

            # ── Delegate the actual cycle to clickbot.run_cycle() ────────
            #    This function itself:
            #      - opens ONE browser ONCE at cycle start
            #      - tries up to N different keywords in the same driver
            #      - only closes the browser in a cycle-level finally
            #      - appends session_summary.txt
            clicks = 0
            try:
                clicks = run_cycle(config, logger, cycle_number, use_proxy=use_proxy)
            except KeyboardInterrupt:
                raise
            except Exception as cycle_err:
                logger.error(f"CYCLE #{cycle_number} crashed (continuing after interval): {cycle_err}")
                stats["status"] = "error"
                clicks = 0

            total_clicks += clicks
            stats["total_clicks"] = total_clicks
            stats["ads_found"]   = max(stats["ads_found"], clicks)   # reasonable approximation

            # Persist last_run_info after EVERY cycle — guarantees user can
            # always copy current totals & paths even from Logs tab.
            try:
                write_last_run_info(
                    config, cycle_number, total_clicks,
                    extra=(
                        f"Status: Running. Next cycle in {interval // 60} minutes.\n"
                        f"Latest cycle (#{cycle_number}) clicks: {clicks}"
                    ),
                )
            except Exception:
                pass

            # Add a short entry to activity_log (UI History panel)
            entry = {
                "time":    datetime.now().strftime("%H:%M"),
                "keyword": f"{first_kw}" + (f" +{max_attempts-1} more" if max_attempts > 1 else ""),
                "found":   clicks,      # best effort — exact per-attempt not needed for history
                "clicked": clicks,
                "cycle":   cycle_number,
            }
            activity_log.insert(0, entry)
            activity_log = activity_log[:50]

            logger.info(
                f"=== CYCLE #{cycle_number} END | "
                f"Clicked: {clicks} | Running total: {total_clicks} ==="
            )

            if stop_event.is_set():
                break

            # Countdown between cycles
            stats["status"] = "running"
            for remaining in range(interval, 0, -1):
                if stop_event.is_set():
                    break
                stats["next_cycle_secs"] = remaining
                time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        # Always write final STOPPED summary + last_run_info (exactly like CLI)
        try:
            stop_line = (
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"STOPPED | Total cycles: {cycle_number} | Total clicks: {total_clicks}"
            )
            append_session_summary(config, [stop_line, ""])
        except Exception:
            pass
        try:
            write_last_run_info(
                config, cycle_number, total_clicks,
                extra=f"Status: STOPPED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )
        except Exception:
            pass

        stats["status"]  = "stopped"
        stats["next_cycle_secs"] = 0
        bot_running = False
        logger.info(f"Bot stopped. Total cycles: {cycle_number} | Total clicks: {total_clicks}")


# ── Python API (exposed to JavaScript) ───────────────────────────────────────

class BotAPI:
    """All methods here are callable from the JavaScript frontend."""

    # ── Bot control ───────────────────────────────────────────────────────────

    def start_bot(self, no_proxy=False):
        global bot_thread, bot_running, stop_event
        if bot_running:
            return {"ok": False, "msg": "Bot is already running."}
        stop_event.clear()
        bot_running = True
        # Respect config proxy.enabled flag unless caller explicitly sets no_proxy
        if not no_proxy:
            try:
                cfg = load_config(CONFIG_PATH)
                no_proxy = not cfg.get("proxy", {}).get("enabled", True)
            except Exception:
                pass
        use_proxy   = not no_proxy
        bot_thread  = threading.Thread(target=bot_worker, args=(use_proxy,), daemon=True)
        bot_thread.start()
        mode = "no proxy (test mode)" if not use_proxy else "Oxylabs proxy"
        return {"ok": True, "msg": f"Bot started ({mode})."}

    def stop_bot(self):
        global bot_running
        if not bot_running:
            return {"ok": False, "msg": "Bot is not running."}
        stop_event.set()
        return {"ok": True, "msg": "Stop signal sent."}

    # ── Status polling ────────────────────────────────────────────────────────

    def get_status(self):
        return {
            "stats":        stats,
            "activity_log": activity_log[:10],
            "bot_running":  bot_running,
        }

    def get_logs(self):
        """Drain the log queue and return all pending messages."""
        messages = []
        while not LOG_QUEUE.empty():
            try:
                messages.append(LOG_QUEUE.get_nowait())
            except queue.Empty:
                break
        return messages

    # ── Log paths + content (for copyable UI buttons) ──────────────────────

    def _log_path(self):
        cfg = load_config(CONFIG_PATH)
        log_file = cfg.get("logging", {}).get("log_file", "clickbot.log")
        if not os.path.isabs(log_file):
            log_file = os.path.join(BASE_DIR, log_file)
        return log_file

    def _summary_path(self):
        return os.path.join(BASE_DIR, "session_summary.txt")

    def _lastrun_path(self):
        return os.path.join(BASE_DIR, "last_run_info.txt")

    def _read_file(self, path, max_lines=None):
        try:
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if max_lines is None:
                    return f.read()
                lines = f.readlines()
                if len(lines) <= max_lines:
                    return "".join(lines)
                return "".join(lines[-max_lines:])
        except Exception as e:
            return f"<error reading file: {e}>"

    def get_log_paths(self):
        """Return absolute paths to all 3 log/summary files for the UI to display."""
        try:
            return {
                "ok": True,
                "log_file":     self._log_path(),
                "summary_file": self._summary_path(),
                "lastrun_file": self._lastrun_path(),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def get_log_tail(self, n=200):
        """Return the last N lines of the main clickbot.log file."""
        try:
            n = int(n) if n else 200
            return {
                "ok": True,
                "content": self._read_file(self._log_path(), max_lines=n),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e), "content": ""}

    def get_summary_contents(self):
        """Return the full contents of session_summary.txt."""
        try:
            return {
                "ok": True,
                "content": self._read_file(self._summary_path()),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e), "content": ""}

    def get_lastrun_contents(self):
        """Return the full contents of last_run_info.txt."""
        try:
            return {
                "ok": True,
                "content": self._read_file(self._lastrun_path()),
            }
        except Exception as e:
            return {"ok": False, "msg": str(e), "content": ""}

    # ── Config / Settings ─────────────────────────────────────────────────────

    def get_config(self):
        try:
            config = load_config(CONFIG_PATH)
            # Mask password for security
            if config.get("proxy", {}).get("password"):
                config["proxy"]["password"] = "••••••••"
            return {"ok": True, "config": config}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def save_config(self, data):
        try:
            # Load existing to preserve password if masked
            existing = load_config(CONFIG_PATH)
            incoming_pwd = data.get("proxy", {}).get("password", "")
            # Detect masked password — any string made entirely of bullet chars
            is_masked = incoming_pwd and all(c in ('\u2022', '•', '*', '●') for c in incoming_pwd)
            if is_masked:
                data["proxy"]["password"] = existing["proxy"]["password"]
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return {"ok": True, "msg": "Settings saved!"}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # ── Proxy test ────────────────────────────────────────────────────────────

    def test_proxy(self):
        try:
            import requests
            config    = load_config(CONFIG_PATH)
            proxy_str = build_proxy_string(config["proxy"])

            # Show what we're using (hide password)
            display = proxy_str.split("@")[-1]   # just host:port
            user_part = proxy_str.split(":")[0]  # username only

            proxies = {"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"}
            headers = {"User-Agent": "Mozilla/5.0"}

            try:
                ip_resp = requests.get(
                    "https://api.ipify.org?format=json",
                    proxies=proxies, headers=headers, timeout=15
                )
            except Exception as conn_err:
                err_str = str(conn_err)
                if "407" in err_str:
                    return {
                        "ok": False, "ip": None,
                        "msg": (
                            f"❌ 407 Proxy Auth Failed.\n"
                            f"Username tried: {user_part}\n"
                            f"Check your Oxylabs username/password are correct."
                        )
                    }
                return {"ok": False, "ip": None, "msg": f"❌ Connection error: {err_str[:200]}"}

            ip      = ip_resp.json().get("ip", "unknown")
            geo_resp = requests.get(f"https://ipapi.co/{ip}/json/", timeout=10)
            geo      = geo_resp.json()
            country  = geo.get("country_name", "Unknown")
            city     = geo.get("city", "Unknown")
            org      = geo.get("org", "Unknown")

            uk_ok  = "United Kingdom" in country
            result = {
                "ok":      uk_ok,
                "ip":      ip,
                "country": country,
                "city":    city,
                "org":     org,
                "msg":     f"✅ UK Proxy OK! IP: {ip} ({city}, {country})\nISP: {org}" if uk_ok
                           else f"⚠️ Connected but not UK. Got: {country} ({city})",
            }
            return result
        except Exception as e:
            return {"ok": False, "ip": None, "msg": f"❌ Proxy test error: {str(e)[:300]}"}

    def test_direct(self):
        """Test internet connectivity without any proxy."""
        try:
            import requests
            resp = requests.get(
                "https://api.ipify.org?format=json",
                timeout=10
            )
            ip = resp.json().get("ip", "unknown")
            return {
                "ok": True,
                "ip": ip,
                "msg": f"✅ Direct connection works! Your real IP: {ip}"
            }
        except Exception as e:
            return {"ok": False, "ip": None, "msg": f"❌ No internet connection: {str(e)[:200]}"}


# ── App entry point ───────────────────────────────────────────────────────────

def main():
    api      = BotAPI()
    ui_path  = os.path.join(BASE_DIR, "ui", "index.html")
    ui_url   = f"file:///{ui_path.replace(os.sep, '/')}"

    window = webview.create_window(
        title      = "🔒 Locksmith Ad Killer",
        url        = ui_url,
        js_api     = api,
        width      = 1100,
        height     = 720,
        min_size   = (900, 600),
        resizable  = True,
        background_color = "#0d1117",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass   # User closed the window — normal exit
    except Exception as fatal:
        # Show a minimal error window instead of crashing silently
        import traceback
        err_html = f"""
        <html><body style='background:#0d1117;color:#ff4757;
          font-family:monospace;padding:40px;'>
        <h2>Startup Error</h2>
        <pre style='background:#161b22;padding:20px;
          border-radius:8px;color:#e6edf3;white-space:pre-wrap;'>
{traceback.format_exc()}
        </pre>
        </body></html>"""
        try:
            err_win = webview.create_window(
                title  = "Error — Locksmith Ad Killer",
                html   = err_html,
                width  = 900, height = 500,
            )
            webview.start()
        except Exception:
            pass
