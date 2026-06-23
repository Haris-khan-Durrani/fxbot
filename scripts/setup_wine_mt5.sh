#!/bin/bash
# scripts/setup_wine_mt5.sh
# ─────────────────────────────────────────────────────────────────
# Sets up Wine + MetaTrader5 on Ubuntu/Debian Linux.
# Run as root or with sudo.
# After running this script, manually install MT5 terminal via Wine,
# then update MT5_PATH in your .env file.
# ─────────────────────────────────────────────────────────────────

set -euo pipefail

echo "═══════════════════════════════════════════════════════"
echo "  FX Bot — Wine + MT5 Setup Script"
echo "  OS: Ubuntu/Debian (64-bit)"
echo "═══════════════════════════════════════════════════════"

# ── Step 1: Install Wine ──────────────────────────────────────────
echo ""
echo "Step 1: Installing Wine ..."

# Enable 32-bit architecture (required for MT5)
sudo dpkg --add-architecture i386

# Add Wine repository
sudo apt-get update -qq
sudo apt-get install -y wget gpg
wget -qO - https://dl.winehq.org/wine-builds/winehq.key | sudo apt-key add -

# Detect Ubuntu version
UBUNTU_VERSION=$(lsb_release -cs 2>/dev/null || echo "focal")
echo "Detected Ubuntu codename: $UBUNTU_VERSION"
sudo add-apt-repository -y "deb https://dl.winehq.org/wine-builds/ubuntu/ $UBUNTU_VERSION main"

sudo apt-get update -qq
sudo apt-get install -y --install-recommends winehq-stable

echo "Wine version: $(wine --version)"

# ── Step 2: Configure Wine prefix ────────────────────────────────
echo ""
echo "Step 2: Creating Wine prefix (64-bit) ..."

export WINEPREFIX="$HOME/.wine_mt5"
export WINEARCH="win64"

winecfg /v win10 2>/dev/null || true   # Set Windows version to 10, ignore errors
echo "WINEPREFIX: $WINEPREFIX"

# ── Step 3: Install dependencies inside Wine ─────────────────────
echo ""
echo "Step 3: Installing required Windows DLLs ..."

# Install winetricks
if ! command -v winetricks &>/dev/null; then
    wget -q https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks \
         -O /usr/local/bin/winetricks
    chmod +x /usr/local/bin/winetricks
fi

WINEPREFIX="$HOME/.wine_mt5" winetricks -q vcrun2019 corefonts || true

# ── Step 4: Download MT5 installer ───────────────────────────────
echo ""
echo "Step 4: Downloading MetaTrader5 installer ..."

MT5_INSTALLER="/tmp/mt5setup.exe"
if [ ! -f "$MT5_INSTALLER" ]; then
    wget -q "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
         -O "$MT5_INSTALLER"
    echo "Downloaded: $MT5_INSTALLER"
else
    echo "Installer already exists: $MT5_INSTALLER"
fi

# ── Step 5: Install MT5 via Wine ─────────────────────────────────
echo ""
echo "Step 5: Installing MT5 terminal via Wine ..."
echo "    (GUI installer will appear — click 'Next' through it)"
echo "    Install path: C:\\Program Files\\MetaTrader 5\\"
echo ""

WINEPREFIX="$HOME/.wine_mt5" wine "$MT5_INSTALLER"

MT5_EXE="$HOME/.wine_mt5/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_EXE" ]; then
    echo "✅ MT5 terminal installed at: $MT5_EXE"
else
    echo "⚠️  MT5 executable not found at expected path."
    echo "    Check: $HOME/.wine_mt5/drive_c/Program Files/"
fi

# ── Step 6: Install Python MetaTrader5 package ───────────────────
echo ""
echo "Step 6: Installing MetaTrader5 Python package ..."

# The MetaTrader5 package needs to find the MT5 terminal
pip install MetaTrader5 || pip3 install MetaTrader5

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Setup complete!"
echo ""
echo "  NEXT STEPS:"
echo "  1. Open MT5 via Wine, log into your Vantage FX demo account:"
echo "     WINEPREFIX=$HOME/.wine_mt5 wine '$MT5_EXE'"
echo ""
echo "  2. Update your .env file:"
echo "     MT5_PATH=$MT5_EXE"
echo ""
echo "  3. Test the connection:"
echo "     python -m src.data.mt5_connection"
echo ""
echo "  4. Run the backtester (Phase 0):"
echo "     python scripts/run_backtest.py"
echo "═══════════════════════════════════════════════════════"
