# Grafana Setup Guide — FX Bot Dashboard

## Step 1: Install Grafana

**Option A — Docker (recommended):**
```bash
docker run -d \
  --name grafana \
  -p 3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=your_password \
  grafana/grafana-oss:latest
```

**Option B — apt (Ubuntu/Debian):**
```bash
sudo apt-get install -y apt-transport-https software-properties-common wget
wget -q -O - https://packages.grafana.com/gpg.key | sudo apt-key add -
echo "deb https://packages.grafana.com/oss/deb stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install grafana
sudo systemctl enable --now grafana-server
```

Access Grafana at: `http://YOUR_VPS_IP:3000` (default login: `admin` / `admin`)

## Step 2: Install MySQL Data Source Plugin

1. Go to **Configuration → Data Sources → Add data source**
2. Search for **MySQL**
3. Configure:
   - **Host:** `localhost:3306`
   - **Database:** `fxbot`
   - **User:** `fxbot`
   - **Password:** *(your MySQL password)*
4. Click **Save & Test** — should show "Database Connection OK"

## Step 3: Import the Pre-built Dashboard

1. Go to **Dashboards → Import**
2. Upload `deploy/grafana_dashboard.json`
3. Select your MySQL data source
4. Click **Import**

## Dashboard Panels

| Panel | Query |
|---|---|
| Live Equity Curve | `daily_stats.ending_balance` over time |
| Win Rate Gauge | Win / (Win + Loss) from `trade_history` |
| Daily P&L Bar Chart | `daily_stats.pnl_usd` per day |
| Per-Pair Trade Distribution | `trade_history` grouped by symbol |
| Signal Score Histogram | `signals.score` distribution |
| Open Positions | `trades` current open |
| Weekly Performance | `performance_metrics` weekly rows |

## Step 4: Set Up Alerts (Optional)

In Grafana, create alert rules on:
- **Daily loss > 3%** → Telegram notification (via Grafana webhook)
- **No heartbeat in 25h** → Email/Telegram

## Security Note

If your VPS is public, restrict Grafana access:
```bash
# Only allow access from your IP
sudo ufw allow from YOUR_IP to any port 3000
```
Or use Nginx as a reverse proxy with HTTPS.
