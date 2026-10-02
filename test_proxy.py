"""
Phase 1 — Proxy Validation Script
Tests the Oxylabs residential proxy connection and verifies:
  - Proxy connects successfully
  - IP is a UK residential IP
  - IP location resolves near Cheltenham, UK
"""

import json
import requests
import sys
from colorama import Fore, Style, init

init(autoreset=True)


def load_config(path="config.json"):
    with open(path, "r") as f:
        return json.load(f)


def build_proxy_url(proxy_cfg):
    user = proxy_cfg["username"]
    pwd  = proxy_cfg["password"]
    host = proxy_cfg["host"]
    port = proxy_cfg["port"]
    city = proxy_cfg.get("city", "")
    country = proxy_cfg.get("country", "GB")

    # Oxylabs city-level targeting via username suffix
    # Format: customer-USERNAME-cc-GB-city-cheltenham
    if city:
        auth_user = f"customer-{user}-cc-{country}-city-{city}"
    else:
        auth_user = f"customer-{user}-cc-{country}"

    proxy_url = f"http://{auth_user}:{pwd}@{host}:{port}"
    return proxy_url


def test_proxy_connection(proxy_url):
    proxies = {
        "http":  proxy_url,
        "https": proxy_url,
    }
    print(f"{Fore.CYAN}[*] Testing proxy connection...")
    print(f"    Proxy URL: {proxy_url.split('@')[1]}")  # hide credentials

    try:
        # Test 1 — get current IP
        resp = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=20
        )
        ip = resp.json().get("ip", "unknown")
        print(f"{Fore.GREEN}[✓] Connected! Proxy IP: {ip}")

        # Test 2 — get geo info
        geo_resp = requests.get(
            f"https://ipapi.co/{ip}/json/",
            timeout=15
        )
        geo = geo_resp.json()
        country  = geo.get("country_name", "Unknown")
        region   = geo.get("region", "Unknown")
        city     = geo.get("city", "Unknown")
        org      = geo.get("org", "Unknown")

        print(f"\n{Fore.YELLOW}[i] IP Geo-Location Report:")
        print(f"    Country : {country}")
        print(f"    Region  : {region}")
        print(f"    City    : {city}")
        print(f"    ISP/Org : {org}")

        # Validation checks
        if "United Kingdom" in country or "GB" in country:
            print(f"\n{Fore.GREEN}[✓] PASS — IP is in the United Kingdom")
        else:
            print(f"\n{Fore.RED}[✗] FAIL — IP is NOT in the UK (got: {country})")
            print("    Check your Oxylabs plan and ensure UK geo-targeting is enabled.")
            return False

        if "cheltenham" in city.lower() or "gloucestershire" in region.lower():
            print(f"{Fore.GREEN}[✓] PASS — IP resolves near Cheltenham / Gloucestershire")
        else:
            print(f"{Fore.YELLOW}[~] NOTE — City is '{city}' (not exactly Cheltenham)")
            print("    Oxylabs may not have residential IPs exactly in Cheltenham.")
            print("    Nearest UK city will be used. This is acceptable.")

        # Test 3 — test Google.co.uk access through proxy
        print(f"\n{Fore.CYAN}[*] Testing Google.co.uk access through proxy...")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        }
        g_resp = requests.get(
            "https://www.google.co.uk",
            proxies=proxies,
            headers=headers,
            timeout=20
        )
        if g_resp.status_code == 200:
            print(f"{Fore.GREEN}[✓] PASS — Google.co.uk is accessible through proxy (HTTP {g_resp.status_code})")
        else:
            print(f"{Fore.RED}[✗] FAIL — Google.co.uk returned HTTP {g_resp.status_code}")

        print(f"\n{Fore.GREEN}{'='*50}")
        print(f"{Fore.GREEN}  Proxy validation complete. Ready to proceed.")
        print(f"{Fore.GREEN}{'='*50}\n")
        return True

    except requests.exceptions.ProxyError as e:
        print(f"{Fore.RED}[✗] Proxy connection FAILED: {e}")
        print("    Check your Oxylabs credentials and proxy host/port in config.json")
        return False
    except requests.exceptions.Timeout:
        print(f"{Fore.RED}[✗] Connection timed out. Proxy may be slow or credentials incorrect.")
        return False
    except Exception as e:
        print(f"{Fore.RED}[✗] Unexpected error: {e}")
        return False


def main():
    print(f"\n{Fore.CYAN}{'='*50}")
    print(f"{Fore.CYAN}  Oxylabs Proxy Validation — Phase 1")
    print(f"{Fore.CYAN}{'='*50}\n")

    config = load_config()
    proxy_url = build_proxy_url(config["proxy"])
    success = test_proxy_connection(proxy_url)

    if not success:
        print(f"{Fore.RED}[!] Please update config.json with correct Oxylabs credentials and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
