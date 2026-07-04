# Deploying the Stock Backtester on Render (always-on, ~$7/month)

This is a complete, from-zero guide to putting the app online at a public URL,
running 24/7 with no "cold start" delays. It assumes you've never deployed
anything before. Follow it top to bottom.

**What it costs:** $7/month for the always-on server + about $0.25/month for a
small disk to hold the database = **~$7.25/month**. The Render account and
"workspace" itself are free.

**The plan in one paragraph:** Your *code* goes on GitHub (free). Render pulls the
code from GitHub and runs it on an always-on server. Your 127 MB database file is
too big for GitHub's normal storage, so we park it as a GitHub *Release* download
and pull it onto a small Render "disk" that survives restarts. That's the whole trick.

---

## Before you start, create two free accounts

1. **GitHub** — https://github.com (this stores your code).
2. **Render** — https://render.com, and click "Get Started" / sign up (you can sign
   up *with* your GitHub account, which makes the later connection step easier).

You'll also need Git installed on your PC. Check by opening a terminal (Command
Prompt or PowerShell on Windows) and typing `git --version`. If it's not found,
install it from https://git-scm.com/download/win and reopen the terminal.

---

## Step 1 — Put your code on GitHub

1. On GitHub, click the **+** (top right) → **New repository**. Name it
   `stockbacktester`, choose **Public** (recommended — it's a portfolio piece, and
   it also makes Step 2 simpler), and **don't** add a README or .gitignore (you
   already have them). Click **Create repository**.
2. In your terminal, go into your project folder (the one containing `run.py`) and run
   these commands one at a time. Replace `YOUR-USERNAME` with your GitHub username:

   ```bash
   git init
   git add .
   git commit -m "Stock backtester"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/stockbacktester.git
   git push -u origin main
   ```

   Your `.gitignore` already excludes `market.db`, so only code is uploaded — the
   database is handled separately in the next step.

## Step 2 — Park the database file as a GitHub "Release"

Your `market.db` is ~127 MB, over GitHub's 100 MB limit for normal files. GitHub
*Releases*, however, allow files up to 2 GB — so we use one as a parking spot.

1. On your repo's GitHub page, click **Releases** (right sidebar) → **Create a new
   release** (or "Draft a new release").
2. Click **Choose a tag**, type `data-v1`, and click **Create new tag**.
3. Give it a title like `Market data`.
4. Drag your `market.db` file (from `backend\data\market.db`) into the
   **"Attach binaries"** box and wait for the upload to finish.
5. Click **Publish release**.
6. On the published release, **right-click** the `market.db` link and **Copy link
   address**. It looks like:
   `https://github.com/YOUR-USERNAME/stockbacktester/releases/download/data-v1/market.db`
   Keep this URL handy — you'll paste it in Step 4.

## Step 3 — Create the web service on Render

1. Go to https://dashboard.render.com. Click **New +** → **Web Service**.
2. Connect your GitHub and select your `stockbacktester` repository.
3. Fill in the form:
   - **Name:** `stockbacktester` (this becomes part of your URL)
   - **Region:** the one nearest you
   - **Branch:** `main`
   - **Root Directory:** leave blank
   - **Runtime / Language:** Python (Render detects this automatically)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app:app --app-dir backend --host 0.0.0.0 --port $PORT`
   - **Instance Type:** choose **Starter ($7/month)**. Do **not** pick Free — the
     free tier has the 1-minute cold-start delay and can't use a disk.
4. Expand the **Advanced** section (near the bottom) and add two things:

   **a) An environment variable** (tells the app where the database lives):
   - Key: `MARKET_DB_PATH`
   - Value: `/var/data/market.db`

   **b) A disk** (click **Add Disk**):
   - Name: `data`
   - Mount Path: `/var/data`
   - Size: `1` GB (the smallest — your DB is 127 MB)

5. Click **Create Web Service**. Render will install dependencies and start the app.
   This takes a few minutes. When it finishes you'll get a URL like
   `https://stockbacktester.onrender.com`.

   The site will load but show errors until the database is in place — that's the
   next step.

## Step 4 — Load the database onto the disk

1. In your service's page on Render, click the **Shell** tab (left menu). This opens
   a command line running *on your server*.
2. Paste this command, replacing the URL with the one you copied in Step 2:

   ```bash
   curl -L -o /var/data/market.db "https://github.com/YOUR-USERNAME/stockbacktester/releases/download/data-v1/market.db"
   ```

3. Check it arrived:

   ```bash
   ls -lh /var/data/market.db
   ```

   You should see a file around **127M**.
4. Reload your `https://...onrender.com` URL. The site is now fully working — charts,
   metrics, backtests, everything. If it still errors, click **Manual Deploy →
   Deploy latest commit** (or **Restart service**) to be safe.

## Step 5 — You're live

Your site is now public, always-on, and served over HTTPS. Share the
`onrender.com` link. Every time you `git push` new code to `main`, Render
automatically redeploys — and because the database is on the disk, it stays put
through redeploys.

### Optional: a custom domain

If you want `yourname.com` instead of `...onrender.com`: buy a domain from any
registrar, then in your Render service go to **Settings → Custom Domains → Add**,
and follow the DNS instructions Render gives you. (Optional, ~$10/year.)

---

## Keeping the data current

The database is a snapshot from whenever you last built it. To refresh it later:

1. On your own PC, update your local database:
   `cd data_pipeline` then `python fetch_data.py --update`.
2. On GitHub, edit your `data-v1` release (or make a new one), delete the old
   `market.db` asset, and upload the new one.
3. In Render's **Shell**, re-run the `curl` command from Step 4 to pull the fresh file.

(Running the data pipeline directly on Render is possible but not recommended:
Yahoo Finance tends to throttle requests coming from datacenter IP addresses, so
building the data on your home machine and re-uploading is the reliable path.)

## Good to know

- **Auto-deploy:** every push to `main` redeploys automatically. Your disk (and its
  database) persists across deploys.
- **Data licensing:** prices come from Yahoo Finance, whose terms restrict public
  *redistribution*. Low practical risk for a personal demo, but consider a small
  "data via Yahoo Finance, for demonstration only" note in the site footer.
- **Cost:** watch your usage in the Render dashboard. A single Starter service plus a
  1 GB disk is about $7.25/month with normal portfolio traffic.

## Troubleshooting

- **502 Bad Gateway:** the start command is wrong or the app isn't binding correctly.
  It must be exactly `uvicorn app:app --app-dir backend --host 0.0.0.0 --port $PORT`
  (the `0.0.0.0` and `$PORT` parts are required).
- **Site loads but no data / errors:** the database isn't on the disk. Re-run the
  `curl` command in the Shell (Step 4), and confirm the `MARKET_DB_PATH` env var is
  `/var/data/market.db` and the disk's mount path is `/var/data` (they must match).
- **Build fails on a dependency:** open the deploy logs. If it's a Python-version
  issue, add an environment variable `PYTHON_VERSION` = `3.11.9` and redeploy.
- **Shell tab missing:** it's only on paid instances — confirm you chose Starter, not
  Free.
