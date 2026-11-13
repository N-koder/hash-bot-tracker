# 🚀 Telegram Channel Alpha Hash Tracker Bot

An ultra-fast, high-concurrency Telegram bot built with **Telethon (MTProto)** and **MongoDB** that monitors designated Telegram channels in real-time and instantly notifies users the exact millisecond a matching hashtag (`#SOL`, `#ETH`, `#0x123...`, `#alpha`) is detected.

Engineered with in-memory caching for **sub-millisecond (<0.1ms)** tag matching and designed for **100% free hosting on Render (with automated 24/7 Keep-Alive)**.

---

## ⚡ Key Features

- **⚡ Sub-Millisecond Hashtag Detection:** High-speed in-memory RAM cache matches incoming channel posts instantly without hitting the database on every post.
- **🔄 Concurrent Async Alerts:** Uses Telethon's native async message dispatcher (`asyncio.gather`) instead of slow blocking synchronous HTTP requests.
- **📥 Forward & Bulk Import:** Forward any message from a channel or chat directly to the bot — it automatically extracts all `#hashtags` along with their nicknames on each line! Or use `/addbulk`.
- **🏷️ Case-Insensitive & Nicknames:** `#BTC` matches `#btc`, `#Btc`, etc. Supports custom nicknames (e.g. `/addhash #0x8a92 Uniswap Pool`).
- **🛡️ Privacy & Multi-User Isolated:** Each user manages their own private hashtag watch list.
- **📢 Rich Notifications:** Formatted alert cards showing the matched hashtag, source channel name, exact timestamp, full message text, and a direct link to the original channel message.
- **🌐 Render Free Tier Ready:**
  - Built-in lightweight HTTP health server listening on `$PORT`.
  - Beautiful live web status dashboard (`/`) and JSON health check (`/healthz`).
  - **Automated Keep-Alive Self-Ping:** Prevents Render free-tier web services from sleeping after 15 minutes of inactivity!
- **👑 Full Admin Control Suite:**
  - View registered user counts & recent users (`/users`).
  - Broadcast announcements to all bot users (`/broadcast <message>`).
  - Block/Unblock abusive users (`/block`, `/unblock`, `/blocked`).
  - Global hashtag tracking overview (`/allhashes`).

---

## 📋 Commands

### 👤 User Commands
| Command | Description | Example |
| :--- | :--- | :--- |
| `/start` | Open the interactive bot control dashboard | `/start` |
| `/addhash #tag [nickname]` | Track a new hashtag (with optional nickname) | `/addhash #SOL Solana Alpha` |
| `/addbulk [hashes]` | Add multiple hashtags & nicknames (multi-line) | `/addbulk \n#BTC Bitcoin\n#ETH Ethereum` |
| Forward Message | Forward any post containing hashtags directly to the bot | *Forward channel post* |
| `/delete #tag` | Stop tracking a hashtag | `/delete #SOL` |
| `/listhash` | List all your active tracked hashtags | `/listhash` |
| `/clear` | Clear all your tracked hashtags (with confirmation) | `/clear` |
| `/stats` | View your statistics and bot uptime | `/stats` |
| `/ping` | Test bot response latency in milliseconds | `/ping` |
| `/help` | Detailed command help and guide | `/help` |

### 👑 Admin Commands (Restricted to `ADMIN_IDS`)
| Command | Description | Example |
| :--- | :--- | :--- |
| `/admin` | Show the admin control panel | `/admin` |
| `/users` | View total registered users and last 10 users | `/users` |
| `/broadcast <text>` | Broadcast an announcement to all registered users | `/broadcast System update complete!` |
| `/block <@user \| id>` | Block a user from using the bot | `/block @spammer` |
| `/unblock <@user \| id>` | Unblock a restricted user | `/unblock @spammer` |
| `/blocked` | List all currently blocked users | `/blocked` |
| `/allhashes` | View all active hashtags across all users | `/allhashes` |

---

## 🛠️ Prerequisites

1. **Telegram API ID & API Hash:** Get them for free from [my.telegram.org](https://my.telegram.org) under *API Development Tools*.
2. **Telegram Bot Token:** Create a bot via [@BotFather](https://t.me/BotFather) on Telegram.
3. **MongoDB Connection URI:** Free cloud database from [MongoDB Atlas](https://www.mongodb.com/cloud/atlas) (M0 Free Tier).

---

## 🔑 Step 1: Generate Telethon `SESSION_STRING`

Render and cloud servers run headlessly without an interactive terminal, meaning Telethon cannot ask for your phone number or OTP code during deployment.

Generate your reusable `SESSION_STRING` locally once:

```bash
# In your local terminal:
python generate_session.py
```
- Enter your `API_ID` and `API_HASH`.
- Enter your phone number with country code and the Telegram login code sent to you.
- Copy the generated `SESSION_STRING` output.

---

## 💻 Step 2: Local Development Setup

1. **Clone and enter repository:**
   ```bash
   cd channel_read_bot
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Fill in your actual values:
   ```env
   API_ID=12345678
   API_HASH=abcdef1234567890abcdef1234567890
   BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
   SESSION_STRING=1BVtsOHQBu7...your_string...
   MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
   CHANNEL_ID=-1001234567890
   CHANNEL="Alpha Callers"
   ADMIN_IDS=1947158378
   PORT=8080
   ```

5. **Run the bot:**
   ```bash
   python bot.py
   ```

---

## ☁️ Step 3: Deploying on Render (100% Free)

You can host this 24/7 on [Render](https://render.com) using a free **Web Service**.

### Method A: Blueprint Deployment (Recommended)
1. Push this repository to GitHub or GitLab.
2. Log into [Render Dashboard](https://dashboard.render.com).
3. Click **New +** > **Blueprint**.
4. Connect your repository. Render will automatically detect `render.yaml`.
5. Fill in your environment variables (`API_ID`, `API_HASH`, `BOT_TOKEN`, `MONGO_URI`, `SESSION_STRING`, `CHANNEL_ID`, `ADMIN_IDS`).
6. Click **Apply**.

### Method B: Manual Web Service Deployment
1. In Render Dashboard, click **New +** > **Web Service**.
2. Connect your Git repository.
3. Configure the settings:
   - **Name:** `telegram-hash-tracker`
   - **Region:** Any (e.g. Oregon or Frankfurt)
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** `Free`
4. Under **Environment Variables**, add:
   - `API_ID`: your API ID
   - `API_HASH`: your API Hash
   - `BOT_TOKEN`: your Bot Token
   - `MONGO_URI`: your MongoDB Atlas URI
   - `SESSION_STRING`: string generated via `generate_session.py`
   - `CHANNEL_ID`: channel ID to monitor (e.g. `-1001234567890` or `@channel_name`)
   - `CHANNEL`: display name of channel
   - `ADMIN_IDS`: your Telegram ID (e.g. `1947158378`)
   - `PORT`: `10000`
5. Click **Create Web Service**.

---

## ⏰ 24/7 Keep-Alive on Render Free Tier

Render's free web services automatically spin down (sleep) after 15 minutes without incoming HTTP traffic.

**This bot has two built-in ways to stay awake 24/7 for free:**

### Option 1: Automatic Self-Ping (Zero External Setup)
1. Once your Render web service is deployed, copy its public URL (e.g., `https://telegram-hash-tracker.onrender.com`).
2. In Render dashboard, go to **Environment** for your service and set:
   ```env
   KEEP_ALIVE_URL=https://telegram-hash-tracker.onrender.com
   ```
3. The bot will automatically send a lightweight GET request to its `/health` endpoint every 10 minutes, keeping the Render free service active **permanently** without sleeping!

### Option 2: External Uptime Monitor (Optional Backup)
You can also use a free uptime monitor:
1. Create a free account on [UptimeRobot](https://uptimerobot.com) or [cron-job.org](https://cron-job.org).
2. Add a new HTTP monitor pointing to:
   `https://your-bot-service.onrender.com/healthz`
3. Set the interval to **5 minutes** or **10 minutes**.

---

## 🔒 Security Best Practices

- **Never** commit your `.env` file or session strings to GitHub.
- Keep `SESSION_STRING` strictly confidential — it grants access to your Telegram user client.
- The built-in `/block` and `/unblock` commands safeguard against spam or unauthorized use.
