"""
scripts/test_network.py
────────────────────────
Network diagnostics script to troubleshoot Telegram API connectivity.
Run using: python scripts/test_network.py
"""
from __future__ import annotations

import os
import socket
import urllib.request
import urllib.error
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

def run_diagnostics():
    load_dotenv(".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    proxy_url = os.environ.get("TELEGRAM_PROXY_URL", "")

    print("=" * 60)
    print("           Telegram API Connectivity Diagnostics")
    print("=" * 60)
    
    # 1. Check DNS Resolution
    print("\n1. Checking DNS Resolution for api.telegram.org...")
    try:
        ip_list = socket.getaddrinfo("api.telegram.org", 443)
        ips = list(set([ip[4][0] for ip in ip_list]))
        print(f"   ✅ DNS Resolved successfully to: {', '.join(ips)}")
    except Exception as e:
        print(f"   ❌ DNS Resolution Failed: {e}")
        print("      This usually means DNS hijacking or complete local block.")
        return

    # 2. Check TCP Socket Connection
    print("\n2. Checking TCP port 443 connection to api.telegram.org...")
    success_tcp = False
    for ip in ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((ip, 443))
            s.close()
            print(f"   ✅ TCP Connection to {ip}:443 succeeded.")
            success_tcp = True
            break
        except Exception as e:
            print(f"   ❌ TCP Connection to {ip}:443 failed: {e}")
    
    if not success_tcp:
        print("   ❌ All TCP connection attempts failed.")
        print("      Your firewall or ISP is dropping packets to Telegram.")
    
    # 3. Check HTTPS request (Direct)
    print("\n3. Testing Direct HTTPS Request to api.telegram.org...")
    url = "https://api.telegram.org"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            print(f"   ✅ Direct HTTPS Request succeeded: Code {response.status}")
    except urllib.error.URLError as e:
        print(f"   ❌ Direct HTTPS Request Failed: {e.reason}")
    except Exception as e:
        print(f"   ❌ Direct HTTPS Request Failed with error: {e}")

    # 4. Check HTTPS request with Proxy (if configured)
    if proxy_url:
        print(f"\n4. Testing HTTPS Request via Proxy ({proxy_url})...")
        try:
            proxy_handler = urllib.request.ProxyHandler({'https': proxy_url, 'http': proxy_url})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with opener.open(req, timeout=5.0) as response:
                print(f"   ✅ HTTPS Request via Proxy succeeded: Code {response.status}")
        except Exception as e:
            print(f"   ❌ Proxy HTTPS Request Failed: {e}")
    else:
        print("\n4. No TELEGRAM_PROXY_URL configured in .env (skipping proxy test).")

    print("\n" + "=" * 60)
    print("                    Recommendations")
    print("=" * 60)
    if success_tcp:
        print("👉 The server is reachable, but requests might be blocked or timing out.")
        print("   If you are running a VPN, verify it is turned ON and working for all traffic.")
    else:
        print("👉 The connection is completely blocked at the network layer by your ISP.")
        print("   To solve this locally:")
        print("   A) Enable a VPN (e.g. ProtonVPN, Cloudflare WARP) before running the bot.")
        print("   B) Or add a valid proxy to your .env file:")
        print("      TELEGRAM_PROXY_URL=http://username:password@proxy_host:port")
        print("      (Or socks5://username:password@proxy_host:port)")
        print("\n   Note: This block only affects your local PC. Your VPS will not experience this.")
    print("=" * 60)

if __name__ == "__main__":
    run_diagnostics()
