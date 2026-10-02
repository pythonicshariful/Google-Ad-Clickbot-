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

    # Fake user agent
    try:
        ua = UserAgent()
        user_agent = ua.chrome
    except Exception:
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

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
    w = browser_cfg.get("window_width", 1366)
    h = browser_cfg.get("window_height", 768)
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
    # Primary: data-text-ad attribute (most reliable)
    "div[data-text-ad='1']",
    # Secondary: ad label containers
    "div.uEierd",
    # Tertiary: sponsored label approach
    "[aria-label='Ads']",
    # Fallback: top ads block
    "#tads .v5yQqb",
    "#tads li.ads-ad",
    # Additional fallback
    ".pla-unit",
]

LINK_WITHIN_AD_SELECTORS = [
    "a[data-rw]",        # ad click-through link
    "a[href]:not([href='#'])",  # any real link within the ad block
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
    """Navigate to Google.co.uk and perform a search."""
    logger.info(f"Searching: '{keyword}'")
    driver.get("https://www.google.co.uk")
    human_delay(1.5, 3.0)

    accept_google_consent(driver, logger)

    try:
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "q"))
        )
        search_box.clear()
        human_type(search_box, keyword)
        human_delay(0.5, 1.2)
        search_box.send_keys(Keys.RETURN)
        logger.info("Search submitted.")
        human_delay(2.0, 4.0)
        return True
    except TimeoutException:
        logger.error("Search box not found — possible CAPTCHA or block.")
        return False


def detect_ads(driver, logger):
    """
    Detect sponsored ads on the Google results page.
    Returns a list of clickable ad anchor elements.
    """
    ad_links = []

    for selector in AD_SELECTORS:
        try:
            ad_containers = driver.find_elements(By.CSS_SELECTOR, selector)
            if ad_containers:
                logger.info(f"Found {len(ad_containers)} ad container(s) via '{selector}'")
                for container in ad_containers:
                    for link_sel in LINK_WITHIN_AD_SELECTORS:
                        try:
                            links = container.find_elements(By.CSS_SELECTOR, link_sel)
                            for link in links:
                                href = link.get_attribute("href")
                                if href and href.startswith("http"):
                                    ad_links.append((link, href))
                                    break  # one link per ad container
                        except Exception:
                            continue
                if ad_links:
                    break  # found ads, stop trying selectors
        except Exception:
            continue

    if not ad_links:
        logger.warning("No sponsored ad links detected on this results page.")
    else:
        logger.info(f"Total sponsored ad links found: {len(ad_links)}")

    return ad_links


def click_ad(driver, link_element, href, config, logger):
    """
    Click a single ad link, wait on the destination page, then go back.
    """
    behavior = config["behavior"]
    wait_min = behavior.get("wait_on_ad_page_seconds_min", 5)
    wait_max = behavior.get("wait_on_ad_page_seconds_max", 15)

    original_window = driver.current_window_handle
    all_windows_before = set(driver.window_handles)

    try:
        logger.info(f"  → Clicking ad: {href[:80]}...")
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


# ─────────────────────────────────────────────────────────────────────────────
# ONE FULL CYCLE
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(config, logger, cycle_number, use_proxy=True):
    """
    Execute one full bot cycle:
    1. Pick a random keyword
    2. Launch browser with fresh proxy session (or no proxy in test mode)
    3. Search Google.co.uk
    4. Detect & click all sponsored ads
    5. Log results
    6. Close browser
    """
    keywords     = config["search"]["keywords"]
    behavior_cfg = config["behavior"]
    delay_min    = behavior_cfg.get("min_delay_between_clicks_seconds", 2)
    delay_max    = behavior_cfg.get("max_delay_between_clicks_seconds", 6)

    keyword = random.choice(keywords)

    print(f"\n{Fore.CYAN}{'─'*60}")
    print(f"{Fore.CYAN}  CYCLE #{cycle_number}  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Fore.CYAN}  Keyword: {keyword}")
    print(f"{Fore.CYAN}{'─'*60}\n")

    logger.info(f"=== CYCLE #{cycle_number} START | Keyword: '{keyword}' ===")

    driver = None
    ads_clicked = 0

    try:
        driver = create_driver(config, logger, use_proxy=use_proxy)

        # Search Google
        if not search_google(driver, keyword, logger):
            logger.warning("Search failed — skipping this cycle.")
            return 0

        # Detect sponsored ads
        ad_links = detect_ads(driver, logger)

        if not ad_links:
            print(f"{Fore.YELLOW}  [!] No ads found this cycle.")
            logger.info("No ads found. Cycle complete with 0 clicks.")
            return 0

        print(f"{Fore.GREEN}  [✓] Found {len(ad_links)} sponsored ad(s). Clicking...")

        # Click each ad
        for i, (link_elem, href) in enumerate(ad_links, 1):
            print(f"{Fore.YELLOW}  [{i}/{len(ad_links)}] Clicking...")
            success = click_ad(driver, link_elem, href, config, logger)
            if success:
                ads_clicked += 1
            if i < len(ad_links):
                human_delay(delay_min, delay_max)

    except WebDriverException as e:
        logger.error(f"Browser error during cycle: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during cycle: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    logger.info(f"=== CYCLE #{cycle_number} END | Ads clicked: {ads_clicked} ===")
    print(f"\n{Fore.GREEN}  Cycle #{cycle_number} complete — {ads_clicked} ads clicked.\n")
    return ads_clicked


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

    logger.info("Bot started.")
    logger.info(f"Cycle interval: every {interval_minutes} minutes")
    logger.info(f"Keywords loaded: {len(config['search']['keywords'])}")

    cycle_number    = 0
    total_clicks    = 0

    try:
        while True:
            cycle_number += 1
            clicks = run_cycle(config, logger, cycle_number, use_proxy=use_proxy)
            total_clicks += clicks

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
        print(f"\n{Fore.RED}  Bot stopped by user.")
        logger.info(f"Bot stopped. Total cycles: {cycle_number} | Total clicks: {total_clicks}")
        sys.exit(0)


if __name__ == "__main__":
    main()
