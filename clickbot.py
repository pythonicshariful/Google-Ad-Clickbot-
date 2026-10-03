"""
Google Ad Clickbot — Main Bot
Client: Ollie (Fiverr)
Purpose: Search Google.co.uk for locksmith keywords, click all sponsored ads
         through rotating Oxylabs residential proxies, repeat every 20 minutes.

Phases implemented:
  Phase 1 — Proxy integration (Oxylabs rotating residential, UK geo)
  Phase 2 — Browser automation (Selenium + anti-detection)
  Phase 3 — Keyword rotation
  Phase 4 — 20-minute scheduler loop with full logging

Usage:
  python clickbot.py               # Normal mode (requires proxy in config.json)
  python clickbot.py --no-proxy    # Test mode (no proxy, uses your real IP)
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime

from colorama import Fore, Style, init
from fake_useragent import UserAgent
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

init(autoreset=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def setup_logger(log_file="clickbot.log", level="INFO"):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("clickbot")


# ─────────────────────────────────────────────────────────────────────────────
# PROXY BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_proxy_string(proxy_cfg):
    """
    Build Oxylabs proxy connection string with city-level UK geo targeting.
    Oxylabs rotating residential formats:
      Sub-user (no prefix):   USERNAME:PASSWORD@pr.oxylabs.io:7777
      Main account with geo:  customer-USERNAME-cc-GB-city-cheltenham:PASSWORD@pr.oxylabs.io:7777

    We use the username exactly as entered in config.json.
    For geo-targeting, append the country/city suffixes only if the
    username does NOT already contain '-cc-' (i.e. it's a plain sub-user).
    """
    user    = proxy_cfg["username"]
    pwd     = proxy_cfg["password"]
    host    = proxy_cfg["host"]
    port    = proxy_cfg["port"]
    country = proxy_cfg.get("country", "GB")
    city    = proxy_cfg.get("city", "")

    # If username already has geo suffixes, use it as-is
    if "-cc-" in user or user.startswith("customer-"):
        auth_user = user
    else:
        # Plain sub-user: append geo targeting suffixes
        if city:
            auth_user = f"customer-{user}-cc-{country}-city-{city}"
        else:
            auth_user = f"customer-{user}-cc-{country}"

    return f"{auth_user}:{pwd}@{host}:{port}"


# ─────────────────────────────────────────────────────────────────────────────
# BROWSER FACTORY
# ─────────────────────────────────────────────────────────────────────────────

REALISTIC_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BROWSER_WINDOW_SIZES = [
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1280, 720),
]


def pick_browser_profile():
    """Pick a realistic browser profile for this run to reduce obvious automation patterns."""
    return {
        "user_agent": random.choice(REALISTIC_USER_AGENTS),
        "window_size": random.choice(BROWSER_WINDOW_SIZES),
    }


def create_driver(config, logger, use_proxy=True):
    """
    Create a Selenium Chrome driver with:
    - Oxylabs rotating residential proxy (if use_proxy=True)
    - Randomised user-agent
    - Anti-bot-detection settings
    - UK English language
    """
    browser_cfg  = config["browser"]

    if use_proxy:
        proxy_cfg    = config["proxy"]
        proxy_string = build_proxy_string(proxy_cfg)
    else:
        proxy_string = None
        logger.info("[NO-PROXY MODE] Running without proxy — using your real IP.")

    browser_profile = pick_browser_profile()
    user_agent = browser_profile["user_agent"]

    options = Options()

    # ── Proxy ──────────────────────────────────────────────────────────────
    if proxy_string:
        options.add_argument(f"--proxy-server=http://{proxy_string}")

    # ── Anti-detection ─────────────────────────────────────────────────────
    options.add_argument(f"--user-agent={user_agent}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    # ── Language / locale ──────────────────────────────────────────────────
    options.add_argument("--lang=en-GB")
    options.add_experimental_option(
        "prefs", {
            "intl.accept_languages": "en-GB,en",
            "profile.default_content_setting_values.geolocation": 2,
        }
    )

    # ── Window size ────────────────────────────────────────────────────────
    w, h = browser_profile["window_size"]
    w = browser_cfg.get("window_width", w)
    h = browser_cfg.get("window_height", h)
    if browser_cfg.get("headless", False):
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={w},{h}")

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)

    # Patch navigator.webdriver to hide automation
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-GB', 'en'],
                });
            """
        },
    )

    logger.info(f"Browser launched | UA: {user_agent[:60]}...")
    return driver


# ─────────────────────────────────────────────────────────────────────────────
# HUMAN-LIKE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def human_delay(min_s, max_s):
    """Sleep for a random duration to mimic human pacing."""
    t = random.uniform(min_s, max_s)
    time.sleep(t)


def human_pause_jitter(base=1.0, spread=0.8):
    """Add a small, natural pause to the flow without making the bot visibly slow."""
    time.sleep(random.uniform(base - spread, base + spread))


def human_type(element, text, min_delay=0.05, max_delay=0.18):
    """Type text character by character with random delays."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def human_scroll(driver, pixels_min=100, pixels_max=400):
    """Scroll down a random amount."""
    pixels = random.randint(pixels_min, pixels_max)
    driver.execute_script(f"window.scrollBy(0, {pixels});")
    time.sleep(random.uniform(0.3, 0.8))


def human_move_and_click(driver, element):
    """Move mouse to element with offset then click."""
    actions = ActionChains(driver)
    actions.move_to_element_with_offset(
        element,
        random.randint(-5, 5),
        random.randint(-3, 3)
    )
    actions.pause(random.uniform(0.1, 0.4))
    actions.click()
    actions.perform()


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE SEARCH + AD DETECTION
# ─────────────────────────────────────────────────────────────────────────────

# CSS / XPath selectors for sponsored ads.
# Google changes these occasionally — fallbacks are included.
AD_SELECTORS = [
    # ── CSS selectors ─────────────────────────────────────────────────────
    "div[data-text-ad='1']",
    "div[data-text-ad='true']",
    "div[data-text-ad]",
    "#tads div[data-text-ad]",
    "#tads .v5yQqb",
    "#tads .IuoSj.SbEZf.ekNIOe",
    "#tads .IuoSj",
    "#tads[aria-label='Ads'] > div > div",
    "#tvcap .v5yQqb",
    "#bottomads .v5yQqb",
    "#bottomads div[data-text-ad]",
]

AD_XPATHS = [
    # ── XPath fallbacks (more flexible than CSS for Google's obfuscation) ─
    # Any div with data-text-ad inside any ads region
    "//div[@id='tads']//div[starts-with(@data-text-ad, '1') or starts-with(@data-text-ad, 'true')]",
    # Any div that contains an anchor with data-rw attribute (ad click redirect)
    "//div[@id='tads' or @id='tvcap' or @id='bottomads']//a[@data-rw]/ancestor::div[contains(@class, 'v5yQqb') or @data-text-ad][1]",
]

LINK_WITHIN_AD_SELECTORS = [
    "a.sVXRqc",
    "a.taydad",
    "a.tNxQIb",
    "a[data-rw]",
    "a[href*='/aclk?']",
    "a[href]",
    "[role='link']",
]

LINK_WITHIN_AD_XPATHS = [
    ".//a[contains(@class, 'sVXRqc') or contains(@class, 'taydad') or contains(@class, 'tNxQIb')]",
    ".//a[@data-rw or contains(@href, '/aclk?')]",
    ".//a[@href and not(starts-with(@href, '#'))]",
]


def accept_google_consent(driver, logger):
    """Handle Google's cookie consent page (common in UK/EU)."""
    try:
        consent_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[.//span[contains(text(), 'Accept all')]]")
            )
        )
        consent_btn.click()
        logger.info("Google consent accepted.")
        time.sleep(1.5)
    except TimeoutException:
        pass  # No consent dialog, continue


def search_google(driver, keyword, logger):
    """Navigate to Google.co.uk and perform a search with a more human-like retry flow."""
    logger.info(f"Searching: '{keyword}'")

    for attempt in range(2):
        try:
            driver.get("https://www.google.co.uk")
            human_delay(1.5, 3.0)
            accept_google_consent(driver, logger)

            search_box = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            search_box.clear()
            human_type(search_box, keyword)
            human_pause_jitter(0.4, 0.5)
            search_box.send_keys(Keys.RETURN)
            logger.info("Search submitted.")
            human_delay(2.0, 4.0)
            return True
        except (TimeoutException, WebDriverException, AttributeError, ValueError) as exc:
            logger.warning(f"Search attempt {attempt + 1} failed: {exc}")
            try:
                driver.get("about:blank")
            except Exception:
                pass
            if attempt == 0:
                human_pause_jitter(1.2, 0.8)
                continue
            logger.error("Search box not found — possible CAPTCHA or block.")
            return False

    return False


def _sanitize_url(url):
    """Resolve relative ad URLs and unescape HTML entities for display."""
    if not url:
        return ""
    import html as _html
    url = _html.unescape(url.strip())
    if url.startswith("/aclk?") or url.startswith("/search?") or url.startswith("/"):
        url = "https://www.google.co.uk" + url
    return url


def _find_link_in_container(container, seen_ids):
    """
    Given an ad container WebElement, find the best clickable anchor inside it.
    Tries CSS selectors first, then XPath fallbacks.
    Returns (link_element, display_url) or (None, None).
    """
    import html as _html

    # ── CSS selector pass ─────────────────────────────────────────────────
    for link_sel in LINK_WITHIN_AD_SELECTORS:
        try:
            links = container.find_elements(By.CSS_SELECTOR, link_sel)
        except Exception:
            continue
        for link in links:
            try:
                eid = link.id
            except Exception:
                continue
            if eid in seen_ids:
                continue
            href = link.get_attribute("href")
            rw   = link.get_attribute("data-rw")
            pcu  = link.get_attribute("data-pcu")
            display_url = _sanitize_url(rw or href or pcu or "")
            seen_ids.add(eid)
            return link, display_url

    # ── XPath pass ─────────────────────────────────────────────────────────
    for link_xp in LINK_WITHIN_AD_XPATHS:
        try:
            links = container.find_elements(By.XPATH, link_xp)
        except Exception:
            continue
        for link in links:
            try:
                eid = link.id
            except Exception:
                continue
            if eid in seen_ids:
                continue
            href = link.get_attribute("href")
            rw   = link.get_attribute("data-rw")
            pcu  = link.get_attribute("data-pcu")
            display_url = _sanitize_url(rw or href or pcu or "")
            seen_ids.add(eid)
            return link, display_url

    return None, None


def _describe(elem, max_len=160):
    """Return a short string description of a WebElement for debug logging."""
    try:
        tag = elem.tag_name
        cls = elem.get_attribute("class") or ""
        rid = elem.get_attribute("data-rw") or elem.get_attribute("href") or ""
        return f"<{tag} class='{cls[:40]}' url='{rid[:80]}'>"
    except Exception:
        return "<WebElement>"


def detect_ads(driver, logger):
    """
    Detect sponsored ads on the Google results page.
    Returns a list of (clickable_element, display_url) tuples.

    Strategy:
      1. Wait a moment for Google to finish rendering ads (lazy load).
      2. Scan for ad CONTAINERS using CSS selectors, then XPath fallbacks.
      3. For each container, find the best clickable LINK inside.
      4. If 0 ads found, dump the page HTML for debugging.
    """
    import html as _html

    ad_links = []
    seen_ids = set()
    seen_containers = set()

    # ── Step 1: Wait for ads region to render (Google lazy-loads them) ─────
    try:
        WebDriverWait(driver, 8).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#tads, #tvcap, #bottomads")
            or d.find_elements(By.CSS_SELECTOR, "div[data-text-ad]")
        )
        # Then a short, random human-style pause for ad JS to hydrate anchors
        human_delay(1.0, 2.2)
    except TimeoutException:
        logger.warning("[detect_ads] No ads region markers (#tads/data-text-ad) appeared within 8s.")

    # Quick diagnostic: what ads-related top-level IDs actually exist right now?
    present_ids = []
    for mid in ("tads", "tvcap", "bottomads"):
        try:
            if driver.find_elements(By.ID, mid):
                present_ids.append("#" + mid)
        except Exception:
            pass
    # ── Step 2a: Iterate CSS container selectors ───────────────────────────
    for selector in AD_SELECTORS:
        try:
            containers = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        if not containers:
            continue
        logger.info(f"[detect_ads] CSS '{selector}' -> {len(containers)} container(s)")
        for i, container in enumerate(containers):
            try:
                cid = container.id
            except Exception:
                continue
            if cid in seen_containers:
                continue
            seen_containers.add(cid)
            link, url = _find_link_in_container(container, seen_ids)
            if link is not None:
                logger.info(f"  container#{i} -> link: {_describe(link)} url='{url[:100]}'")
                ad_links.append((link, url))
        if ad_links:
            break

    # ── Step 2b: XPath fallbacks (only if CSS yielded nothing) ─────────────
    if not ad_links:
        logger.info("[detect_ads] CSS selectors empty — trying XPath fallbacks...")
        for xpath in AD_XPATHS:
            try:
                containers = driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            if not containers:
                continue
            logger.info(f"[detect_ads] XPath found {len(containers)} container(s)")
            for i, container in enumerate(containers):
                try:
                    cid = container.id
                except Exception:
                    continue
                if cid in seen_containers:
                    continue
                seen_containers.add(cid)
                link, url = _find_link_in_container(container, seen_ids)
                if link is not None:
                    logger.info(f"  xpath-container#{i} -> {_describe(link)} url='{url[:100]}'")
                    ad_links.append((link, url))
            if ad_links:
                break

    # ── Step 2c: Last-ditch fallback: grab ANY <a data-rw> on the page ─────
    if not ad_links:
        logger.info("[detect_ads] Trying last-ditch: ALL anchors with data-rw on the page...")
        try:
            all_rw = driver.find_elements(By.CSS_SELECTOR, "a[data-rw]")
        except Exception:
            all_rw = []
        for link in all_rw:
            try:
                eid = link.id
            except Exception:
                continue
            if eid in seen_ids:
                continue
            rw = link.get_attribute("data-rw") or ""
            if "/aclk?" not in rw:
                continue
            seen_ids.add(eid)
            ad_links.append((link, _sanitize_url(rw)))
        if ad_links:
            logger.info(f"[detect_ads] Last-ditch found {len(ad_links)} ad link(s) via a[data-rw]")

    # ── Step 3: Result reporting / debug dump ──────────────────────────────
    if not ad_links:
        dta_count = 0
        try:
            dta_count = len(driver.find_elements(By.CSS_SELECTOR, "div[data-text-ad]"))
        except Exception:
            pass
        all_a = 0
        try:
            all_a = len(driver.find_elements(By.TAG_NAME, "a"))
        except Exception:
            pass
        logger.warning(
            f"No sponsored ad links detected. "
            f"(div[data-text-ad] on page: {dta_count}, total <a>: {all_a}, tads/bottomads present: {present_ids})"
        )
    else:
        logger.info(f"Total sponsored ad links found: {len(ad_links)}")

    return ad_links


def _find_live_ad_link_by_href(driver, href, logger=None):
    """Re-query the current DOM and return a live element matching the ad URL."""
    target = _sanitize_url(href or "")
    if not target:
        return None

    selectors = [
        "a.sVXRqc",
        "a.taydad",
        "a.tNxQIb",
        "a[data-rw]",
        "a[href*='/aclk?']",
        "a[href]",
        "[role='link']",
    ]

    for selector in selectors:
        try:
            for link in driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    candidate = link.get_attribute("href") or link.get_attribute("data-rw") or ""
                    if not candidate:
                        continue
                    if _sanitize_url(candidate) == target or target in _sanitize_url(candidate):
                        return link
                except Exception:
                    continue
        except Exception:
            continue

    try:
        for link in driver.find_elements(By.XPATH, ".//a[@href or @data-rw]"):
            try:
                candidate = link.get_attribute("href") or link.get_attribute("data-rw") or ""
            except Exception:
                continue
            if _sanitize_url(candidate) == target or target in _sanitize_url(candidate):
                return link
    except Exception:
        pass

    return None


def click_ad(driver, link_element, href, config, logger):
    """
    Click a single ad link, wait on the destination page, then go back.
    Re-resolves the element from the live DOM when Google invalidates the stale
    original reference after the previous ad click.
    """
    behavior = config["behavior"]
    wait_min = behavior.get("wait_on_ad_page_seconds_min", 5)
    wait_max = behavior.get("wait_on_ad_page_seconds_max", 15)

    original_window = driver.current_window_handle
    all_windows_before = set(driver.window_handles)

    try:
        logger.info(f"  → Clicking ad: {href[:80]}...")

        try:
            live_link = _find_live_ad_link_by_href(driver, href, logger)
            if live_link is not None:
                link_element = live_link
        except Exception:
            pass

        human_scroll(driver)
        human_move_and_click(driver, link_element)

        # Wait for new tab or page load
        time.sleep(2)
        all_windows_after = set(driver.window_handles)
        new_windows = all_windows_after - all_windows_before

        if new_windows:
            # Ad opened in a new tab
            new_tab = list(new_windows)[0]
            driver.switch_to.window(new_tab)
            wait_time = random.uniform(wait_min, wait_max)
            logger.info(f"     Opened new tab. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            driver.close()
            driver.switch_to.window(original_window)
        else:
            # Ad opened in same tab
            wait_time = random.uniform(wait_min, wait_max)
            logger.info(f"     Navigated in same tab. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)
            driver.back()
            time.sleep(2)

        logger.info("  ✓ Ad click complete.")
        return True

    except WebDriverException as e:
        logger.error(f"  ✗ Failed to click ad: {e}")
        try:
            driver.switch_to.window(original_window)
        except Exception:
            pass
        return False


def _absolute_log_path(config):
    """Return absolute, copyable path for the active clickbot log file."""
    import os
    log_file = config["logging"].get("log_file", "clickbot.log")
    if not os.path.isabs(log_file):
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_file)
    return log_file


def _project_path(*parts):
    """Build an absolute path relative to the clickbot project folder."""
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _summary_path():
    return _project_path("session_summary.txt")


def _lastrun_path():
    return _project_path("last_run_info.txt")


def write_last_run_info(config, cycles, clicks, extra=""):
    """Write a persistent, copyable last_run_info.txt — stays after console closes."""
    import os
    path = _lastrun_path()
    logp = _absolute_log_path(config)
    sump = _summary_path()
    lines = [
        "Google Ad Clickbot — Last Run Info",
        "==================================",
        f"Written : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Cycles  : {cycles}",
        f"Clicks  : {clicks}",
        f"Mode    : {'Oxylabs proxy' if config.get('proxy',{}).get('enabled',True) else 'No-proxy test mode'}",
        "",
        "File paths (copy into Explorer / VSCode):",
        f"  Log file      -> {logp}",
        f"  Session sum.  -> {sump}",
        f"  Last run info -> {path}",
        "",
        "Latest config keywords:",
    ]
    for kw in (config.get("search", {}).get("keywords") or []):
        lines.append(f"    • {kw}")
    if extra:
        lines.append("")
        lines.append(extra)
    lines.append("")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass  # never let logging crash the bot
    return path


def read_file_tail(path, max_lines=200):
    """Return the last `max_lines` of a text file, or '' if missing/empty."""
    import os
    try:
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) <= max_lines:
            return "".join(lines)
        return "".join(lines[-max_lines:])
    except Exception:
        return ""


def append_session_summary(config, entry_lines):
    """Append one or more lines to session_summary.txt (always overwritable / copyable)."""
    import os
    path = _summary_path()
    header = ""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        header = (
            "Google Ad Clickbot — Session Summary\n"
            f"Log file: {_absolute_log_path(config)}\n"
            f"Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "========================================================================\n"
        )
    try:
        with open(path, "a", encoding="utf-8") as f:
            if header:
                f.write(header)
            for line in entry_lines:
                f.write(line.rstrip() + "\n")
    except Exception:
        pass  # never let logging stop the bot
    return path


def close_driver_safely(driver, logger=None):
    """Close + quit a Selenium driver with every possible guard; never raises."""
    if driver is None:
        return
    try:
        # First close any extra tabs the ad clicks may have left open
        handles = list(driver.window_handles)
        original = handles[0] if handles else None
        for h in handles[1:]:
            try:
                driver.switch_to.window(h)
                driver.close()
            except Exception:
                pass
        if original:
            try:
                driver.switch_to.window(original)
            except Exception:
                pass
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ONE FULL CYCLE  (ONE browser open for the entire cycle; multi-keyword retry)
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(config, logger, cycle_number, use_proxy=True):
    """
    Execute one bot cycle.
      * ONE single Selenium driver is launched at the START of the cycle and
        kept open for ALL keyword retries (browser doesn't close between
        attempts — only closes at the end of the cycle / on crashes).
      * If a keyword yields 0 ads (or search fails / ad click raises), the bot
        does `driver.get(google.co.uk)` — same browser, same proxy — and tries
        the NEXT keyword in the list, up to `max_keyword_attempts` times,
        without waiting the 20-minute interval.
      * `close_driver_safely()` is guaranteed via try/finally around the WHOLE
        cycle, so the browser is never left open even on crashes / exceptions.

    Returns total ads clicked across all keyword attempts in this cycle.
    """
    keywords       = list(config["search"]["keywords"])   # copy, we'll shuffle
    behavior_cfg   = config["behavior"]
    delay_min      = behavior_cfg.get("min_delay_between_clicks_seconds", 2)
    delay_max      = behavior_cfg.get("max_delay_between_clicks_seconds", 6)
    max_attempts   = min(
        int(config["search"].get("max_keyword_attempts_per_cycle", len(keywords))),
        len(keywords),
    )
    random.shuffle(keywords)  # fresh random attempt order each cycle

    print(f"\n{Fore.CYAN}{'─'*60}")
    print(f"{Fore.CYAN}  CYCLE #{cycle_number}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Fore.CYAN}  Attempting up to {max_attempts} keyword(s) — browser stays open all cycle.")
    print(f"{Fore.CYAN}{'─'*60}\n")

    logger.info(f"=== CYCLE #{cycle_number} START | {len(keywords)} keywords available, max attempts={max_attempts} ===")

    driver = None
    total_ads_clicked_this_cycle = 0
    attempts_done = 0
    driver_launched_ok = False

    try:
        # ── Launch ONE driver ONCE at cycle start ─────────────────────────
        try:
            driver = create_driver(config, logger, use_proxy=use_proxy)
            driver_launched_ok = True
        except WebDriverException as launch_err:
            logger.error(f"CYCLE #{cycle_number}: failed to launch browser: {launch_err}")
            print(f"{Fore.RED}  ✗ Browser launch failed. Skipping cycle.{Style.RESET_ALL}")
            return 0

        for attempt_idx, keyword in enumerate(keywords[:max_attempts], start=1):
            attempts_done = attempt_idx
            ads_found  = 0
            ads_clicks = 0

            print(f"{Fore.MAGENTA}  [Attempt {attempt_idx}/{max_attempts}] Keyword: {keyword}{Style.RESET_ALL}")
            logger.info(f"--- CYCLE #{cycle_number} Attempt {attempt_idx}/{max_attempts} | Keyword: '{keyword}' ---")

            attempt_ok = True
            try:
                # Sanity: ensure driver still alive (not closed by crash guard)
                try:
                    _ = driver.title
                except WebDriverException as dead_err:
                    logger.warning(f"Attempt {attempt_idx}: driver died ({dead_err}). Re-launching...")
                    try:
                        driver = create_driver(config, logger, use_proxy=use_proxy)
                    except Exception as relaunch_err:
                        logger.error(f"Attempt {attempt_idx}: re-launch failed: {relaunch_err}")
                        attempt_ok = False

                if attempt_ok:
                    # ── Search Google (re-uses same browser) ───────────
                    try:
                        search_ok = search_google(driver, keyword, logger)
                    except Exception as search_err:
                        logger.error(f"Attempt {attempt_idx}: search_google raised: {search_err}")
                        search_ok = False

                    if not search_ok:
                        logger.warning(f"Attempt {attempt_idx}: search failed — moving to next keyword.")
                        print(f"{Fore.YELLOW}  [!] Search failed for '{keyword}'. Trying next keyword…{Style.RESET_ALL}")
                        # Ensure back on Google homepage for the next retry
                        try:
                            driver.get("about:blank")
                        except Exception:
                            pass
                        continue

                    # ── Detect sponsored ads ────────────────────────────
                    try:
                        ad_links = detect_ads(driver, logger)
                    except Exception as detect_err:
                        logger.error(f"Attempt {attempt_idx}: detect_ads raised: {detect_err}")
                        ad_links = []
                    ads_found = len(ad_links)

                    if not ad_links:
                        logger.info(
                            f"Attempt {attempt_idx}: no ads for '{keyword}' — "
                            f"trying next keyword (if available)."
                        )
                        print(f"{Fore.YELLOW}  [!] No ads for '{keyword}'. Trying next keyword…{Style.RESET_ALL}")
                        try:
                            driver.get("about:blank")
                        except Exception:
                            pass
                        continue

                    print(f"{Fore.GREEN}  [✓] Found {ads_found} sponsored ad(s). Clicking…{Style.RESET_ALL}")

                    # ── Click each ad ──────────────────────────────────
                    for i, (link_elem, href) in enumerate(ad_links, 1):
                        print(f"{Fore.YELLOW}  [{i}/{ads_found}] Clicking…{Style.RESET_ALL}")
                        try:
                            ok = click_ad(driver, link_elem, href, config, logger)
                        except Exception as click_err:
                            logger.error(f"Attempt {attempt_idx} ad#{i}: click_ad raised: {click_err}")
                            ok = False
                        if ok:
                            ads_clicks += 1
                        if i < ads_found:
                            human_delay(delay_min, delay_max)

                    total_ads_clicked_this_cycle += ads_clicks
                    logger.info(
                        f"Attempt {attempt_idx} END | found={ads_found}, clicked={ads_clicks}"
                    )
                    print(
                        f"{Fore.GREEN}  Attempt {attempt_idx} done — "
                        f"{ads_clicks}/{ads_found} ads clicked.{Style.RESET_ALL}"
                    )

                    # If we got clicks, stop retrying (save proxy/keywords).
                    if ads_clicks > 0:
                        break

            except KeyboardInterrupt:
                raise
            except Exception as attempt_err:
                logger.error(f"Attempt {attempt_idx}: unexpected error (continuing): {attempt_err}")
                print(f"{Fore.RED}  ✗ Attempt {attempt_idx} error: {attempt_err}{Style.RESET_ALL}")
                # Try to recover the driver state for the next attempt
                try:
                    driver.get("about:blank")
                    human_delay(0.5, 1.0)
                except Exception:
                    pass
                # Continue to next keyword attempt in the same cycle

    except KeyboardInterrupt:
        raise
    except Exception as cycle_err:
        logger.error(f"CYCLE #{cycle_number}: fatal cycle-level error: {cycle_err}")
        print(f"{Fore.RED}  ✗ Cycle #{cycle_number} error: {cycle_err}{Style.RESET_ALL}")
    finally:
        # ── GUARANTEED browser close at the END of the cycle ──────────────
        if driver is not None:
            try:
                logger.info(f"Closing browser (end of cycle #{cycle_number})...")
            except Exception:
                pass
            close_driver_safely(driver, logger)

    # ── Cycle end summary ────────────────────────────────────────────────
    summary_line = (
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"CYCLE #{cycle_number}  attempts={attempts_done}/{max_attempts}  "
        f"clicks={total_ads_clicked_this_cycle}"
    )
    append_session_summary(config, [summary_line])
    logger.info(
        f"=== CYCLE #{cycle_number} END | "
        f"attempts={attempts_done}/{max_attempts} | "
        f"Total ads clicked this cycle: {total_ads_clicked_this_cycle} ==="
    )
    print(
        f"\n{Fore.GREEN}  Cycle #{cycle_number} complete — "
        f"{total_ads_clicked_this_cycle} ads clicked across {attempts_done} attempt(s).\n{Style.RESET_ALL}"
    )
    return total_ads_clicked_this_cycle


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Google Ad Clickbot")
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Run without proxy (test mode — uses your real IP)"
    )
    args = parser.parse_args()
    use_proxy = not args.no_proxy

    mode_label = "NO-PROXY TEST MODE" if not use_proxy else "Oxylabs Rotating Residential Proxy"

    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════╗
{Fore.CYAN}║         Google Ad Clickbot — Cheltenham UK          ║
{Fore.CYAN}║  {mode_label:<50}║
{Fore.CYAN}╚══════════════════════════════════════════════════════╝
{Style.RESET_ALL}""")

    if not use_proxy:
        print(f"{Fore.YELLOW}  ⚠  Running in NO-PROXY mode — your real IP will be used.")
        print(f"{Fore.YELLOW}     This is for testing only. Use with proxy in production.\n")

    config = load_config()
    logger = setup_logger(
        log_file=config["logging"].get("log_file", "clickbot.log"),
        level=config["logging"].get("log_level", "INFO"),
    )

    interval_minutes = config["search"].get("cycle_interval_minutes", 20)
    interval_seconds = interval_minutes * 60
    log_path        = _absolute_log_path(config)
    summary_path    = append_session_summary(config, [])  # initialises header if new file
    lastrun_path    = write_last_run_info(config, 0, 0, extra="Bot started — waiting for first cycle.")

    logger.info("Bot started.")
    logger.info(f"Cycle interval: every {interval_minutes} minutes")
    logger.info(f"Keywords loaded: {len(config['search']['keywords'])}")
    logger.info(f"Full log file (copy path): {log_path}")
    logger.info(f"Session summary  (copy path): {summary_path}")
    logger.info(f"Last-run info    (copy path): {lastrun_path}")

    print(f"{Fore.CYAN}  ┌──────────────────────────────────────────────────────────┐")
    print(f"{Fore.CYAN}  │  COPYABLE FILE PATHS — paste into Explorer / VSCode      │")
    print(f"{Fore.CYAN}  └──────────────────────────────────────────────────────────┘{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  📄 clickbot.log:")
    print(f"{Fore.WHITE}     {log_path}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  📋 session_summary.txt:")
    print(f"{Fore.WHITE}     {summary_path}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  📤 last_run_info.txt (persists after exit):")
    print(f"{Fore.WHITE}     {lastrun_path}{Style.RESET_ALL}")
    print()

    cycle_number    = 0
    total_clicks    = 0

    try:
        while True:
            cycle_number += 1
            try:
                clicks = run_cycle(config, logger, cycle_number, use_proxy=use_proxy)
            except KeyboardInterrupt:
                raise
            except Exception as cycle_err:
                logger.error(f"CYCLE #{cycle_number} crashed (but we continue): {cycle_err}")
                print(f"{Fore.RED}  ✗ Cycle #{cycle_number} crashed — continuing after interval.{Style.RESET_ALL}")
                clicks = 0
            total_clicks += clicks

            # Keep last_run_info up to date after every single cycle
            try:
                write_last_run_info(
                    config, cycle_number, total_clicks,
                    extra=(
                        f"Status: Running. Next cycle in {interval_minutes} minutes.\n"
                        f"Latest cycle (#{cycle_number}) clicks: {clicks}"
                    ),
                )
            except Exception:
                pass

            logger.info(
                f"Total clicks so far: {total_clicks} | "
                f"Next cycle in {interval_minutes} minutes."
            )
            print(
                f"{Fore.CYAN}  ⏳ Waiting {interval_minutes} minutes before next cycle...\n"
            )

            # Countdown display
            for remaining in range(interval_seconds, 0, -30):
                mins = remaining // 60
                secs = remaining % 60
                print(
                    f"\r{Fore.YELLOW}  Next cycle in: {mins:02d}:{secs:02d}   ",
                    end="",
                    flush=True,
                )
                time.sleep(min(30, remaining))

            print()  # newline after countdown

    except KeyboardInterrupt:
        print(f"\n{Fore.RED}  Bot stopped by user.{Style.RESET_ALL}")
        stop_summary = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"STOPPED | Total cycles: {cycle_number} | Total clicks: {total_clicks}"
        )
        append_session_summary(config, [stop_summary, ""])
        try:
            write_last_run_info(
                config, cycle_number, total_clicks,
                extra=f"Status: STOPPED by user at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )
        except Exception:
            pass
        logger.info(f"Bot stopped. Total cycles: {cycle_number} | Total clicks: {total_clicks}")
        print(f"{Fore.CYAN}  (All logs persisted. Copy paths above.){Style.RESET_ALL}")
        sys.exit(0)


if __name__ == "__main__":
    main()
