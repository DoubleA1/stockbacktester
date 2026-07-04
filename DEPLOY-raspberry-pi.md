# Deploying the Stock Backtester (self-hosted, free)

This guide puts the app online at your own HTTPS URL, running on a Raspberry Pi in
your home, reachable by anyone — with no monthly hosting fee. The only recurring
cost is a domain name (about $10/year) for a stable web address.

## How it works

```
Visitor's browser  ──►  Cloudflare's network  ──►  outbound tunnel  ──►  Raspberry Pi
   (https://you.com)        (HTTPS, DDoS)          (cloudflared)         (FastAPI + market.db)
```

Your Pi runs two things: the **app** (FastAPI/uvicorn, reading `market.db` locally)
and **cloudflared**, a small program that dials *out* to Cloudflare and holds a
connection open. Visitor traffic rides back down that connection. Because the Pi
only makes an outbound connection, you never open a port on your router, you don't
need a static or public IP, and it works even behind your ISP's CGNAT. Cloudflare
supplies HTTPS and DDoS protection for free.

Your 127 MB `market.db` simply lives on the Pi's disk — the app reads it locally and
returns small JSON responses, so the database file never travels anywhere. (This is
why the GitHub 100 MB file-size limit is irrelevant here.)

---

## What you need

- A **Raspberry Pi 3, 4, 5, or Zero 2 W** running **64-bit Raspberry Pi OS**
  (Bookworm or newer). 64-bit matters: it's what lets `pandas`/`numpy`/`scipy`
  install as prebuilt wheels in seconds instead of compiling for an hour.
  Verify after boot with `uname -m` — it must print `aarch64`.
  2 GB+ RAM is comfortable; 1 GB works for low traffic.
- A **domain name** added to **Cloudflare** (free plan). You can register one
  through Cloudflare directly, or use any registrar and point its nameservers at
  Cloudflare. This is needed for a permanent URL. (Cloudflare's free
  `trycloudflare.com` quick tunnels give a random address that changes every
  restart — fine for a quick test, not for something you share.)
- Your project code and your existing `market.db`.

---

## Part 1 — Prepare the Pi

Flash 64-bit Raspberry Pi OS (use Raspberry Pi Imager; enable SSH and set your
username/password in its settings), boot, then SSH in and update:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

Throughout this guide, replace `pi` with the username you chose.

## Part 2 — Get the code onto the Pi

After you've pushed the project to GitHub (see Part 7), clone it:

```bash
cd ~
git clone https://github.com/YOUR-USERNAME/stockbacktester.git
```

`market.db` is **not** in the repo (it's gitignored), so copy it over separately.
From your Windows PC, either use WinSCP (drag-and-drop GUI) or `scp` from PowerShell:

```powershell
scp "C:\Users\cartw\Downloads\stockbacktester\backend\data\market.db" pi@raspberrypi.local:~/stockbacktester/backend/data/market.db
```

(If `raspberrypi.local` doesn't resolve, use the Pi's IP address, e.g. `pi@192.168.1.42`.)

Alternatively, skip the copy and rebuild the data on the Pi in Part 4 — slower, but
hands-off.

## Part 3 — Python environment

```bash
cd ~/stockbacktester
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

On 64-bit Pi OS this pulls prebuilt `aarch64` wheels — no long compiles. If `scipy`
ever fails to build, double-check `uname -m` says `aarch64`; as a fallback you can
use the system package: `sudo apt install -y python3-scipy`.

## Part 4 — Get the data (only if you didn't copy market.db)

```bash
cd ~/stockbacktester/data_pipeline
pip install lxml          # only needed to pull the live S&P 500 list; otherwise a built-in fallback list is used
python fetch_data.py --backfill
```

This takes a while because it deliberately paces requests to respect rate limits.
Copying your existing `market.db` (Part 2) is much faster.

## Part 5 — Run the app as an always-on service

A `systemd` service keeps the app running and restarts it on crash or reboot.

```bash
# Edit the two marked lines (username/paths) first if your user isn't "pi":
nano ~/stockbacktester/deploy/backtester.service

sudo cp ~/stockbacktester/deploy/backtester.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now backtester
sudo systemctl status backtester      # should show "active (running)"
curl http://127.0.0.1:8000/api/health # should return {"status":"ok",...}
```

If `status` shows an error, `journalctl -u backtester -e` shows the logs.

## Part 6 — Put it online with Cloudflare Tunnel

1. Make sure your domain is active in Cloudflare (its nameservers point to
   Cloudflare — the dashboard walks you through this when you add the domain).
2. Go to the Cloudflare **Zero Trust** dashboard → **Networks → Tunnels →
   Create a tunnel → Cloudflared**. Name it (e.g. `backtester`).
3. Cloudflare shows an **install command** for your platform. Choose **Debian /
   arm64** (that's 64-bit Pi OS). It looks like this, and **already contains your
   unique tunnel token** — copy it from the dashboard, don't retype it:

   ```bash
   curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb \
     && sudo dpkg -i cloudflared.deb \
     && sudo cloudflared service install <YOUR-LONG-TOKEN>
   ```

   That installs `cloudflared`, registers it as a service that starts on boot, and
   connects it to Cloudflare. Back in the dashboard the tunnel should turn
   **Healthy**.
4. Still in the tunnel's page, open **Public Hostname → Add a public hostname**:
   - **Subdomain**: e.g. `backtester` (or leave blank to use the root domain)
   - **Domain**: your domain
   - **Service type**: `HTTP`
   - **URL**: `localhost:8000`
   - Save. Cloudflare automatically creates the DNS record and issues the HTTPS
     certificate.
5. Visit `https://backtester.yourdomain.com` — it's live, worldwide.

## Part 7 — Push the code to GitHub

From your project folder (on your PC or the Pi):

```bash
git init
git add .
git commit -m "Stock backtester"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/stockbacktester.git
git push -u origin main
```

`.gitignore` already excludes `market.db`, so only code is published — the database
stays on your Pi.

## Part 8 — Keep the data fresh (optional)

Run a daily incremental update via cron. Make the script executable and schedule it:

```bash
chmod +x ~/stockbacktester/deploy/update-data.sh
crontab -e
```

Add this line (runs every day at 6 AM; adjust the path to your username):

```
0 6 * * * /home/pi/stockbacktester/deploy/update-data.sh >> /home/pi/backtester-update.log 2>&1
```

SQLite handles the app reading while the script writes; at low traffic this is fine.

---

## Things to keep in mind

- **Uptime is now your Pi + your home internet.** If the Pi loses power, sleeps, or
  your internet drops, the site is down. Keep the Pi plugged in and don't let it
  sleep. This is the main trade-off versus a paid host.
- **Security.** Nothing is exposed on your router — the only path in is the outbound
  tunnel, and Cloudflare fronts it with DDoS protection. The app is read-only with
  no logins or user data, so the attack surface is small. Keep the Pi patched
  (`sudo apt update && sudo apt full-upgrade`).
- **Data licensing.** The prices come from Yahoo Finance, whose terms restrict public
  *redistribution*. Low practical risk for a personal portfolio demo, but consider a
  small "data via Yahoo Finance, for demonstration only" note in the footer.
- **Cost.** $0/month hosting; ~$10/year for the domain; a few dollars a year of
  electricity for the Pi.

## Quick troubleshooting

- App won't start: `journalctl -u backtester -e`
- Tunnel not Healthy: `sudo systemctl status cloudflared` and check the Cloudflare dashboard
- Site loads but no data: confirm `market.db` is at `backend/data/market.db` on the Pi
- 502 from Cloudflare: the app isn't running or isn't on port 8000 (`curl http://127.0.0.1:8000/api/health` on the Pi)
