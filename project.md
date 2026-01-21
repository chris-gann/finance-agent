# Personal Spend Tracker with AI Agent - Development Plan

## Overview

This plan outlines building a personal expense tracking system with three components:
1. **Plaid Integration** - Fetches transactions from your bank and Amex accounts
2. **Local Web Dashboard** - Displays live spend totals (day/week/month)
3. **Telegram Bot Agent** - Allows natural language commands to adjust transaction amounts

---

## Prerequisites & Setup

### MCP Servers to Connect to Claude Code

1. **context7** Utilize the context7 MCP for up-to-date documentation on Plaid and Telegram API

### API Keys You'll Need

1. **Plaid** (sandbox for testing, then development mode - this is are already set up)
   - Sign up at https://dashboard.plaid.com
   - Get `PLAID_CLIENT_ID` and `PLAID_SECRET`
   - You'll need to link your accounts via Plaid Link

2. **Telegram Bot**
   - Message @BotFather on Telegram
   - Create a new bot, get the `TELEGRAM_BOT_TOKEN`

3. **Anthropic API** (for the agent's reasoning)
   - Get `ANTHROPIC_API_KEY` from console.anthropic.com

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Plaid API     │────▶│   SQLite DB      │◀────│  Telegram Bot   │
│ (transactions)  │     │ (transactions +  │     │  (LLM agent)    │
└─────────────────┘     │  adjustments)    │     └─────────────────┘
                        └────────┬─────────┘
                                 │
                        ┌────────▼─────────┐
                        │  Flask Web UI    │
                        │ (live dashboard) │
                        └──────────────────┘
```

---

## File Structure

```
spend-tracker/
├── config.py           # Environment variables and settings
├── database.py         # SQLite setup and queries
├── plaid_client.py     # Plaid API integration
├── agent.py            # LLM agent for transaction adjustments
├── telegram_bot.py     # Telegram bot handler
├── web_app.py          # Flask dashboard
├── sync_transactions.py # Background sync job
├── requirements.txt
├── .env                # API keys (gitignored)
└── run.py              # Main entry point
```

---

## Implementation Plan

### Phase 1: Project Setup

**Step 1.1: Create project structure and requirements.txt**

```
plaid-python>=14.0.0
flask>=3.0.0
python-telegram-bot>=20.0
anthropic>=0.18.0
python-dotenv>=1.0.0
apscheduler>=3.10.0
```

**Step 1.2: Create .env template** (I have already created this an added the tokens)

```
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_secret
PLAID_ENV=sandbox
ANTHROPIC_API_KEY=your_key
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

### Phase 2: Database Layer

**Step 2.1: Create database.py**

- Use SQLite for simplicity (single file, no server)
- Two tables:
  - `transactions`: stores raw Plaid transactions
  - `adjustments`: stores user overrides (transaction_id, adjusted_amount, reason)

**Schema:**
```sql
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT,
    amount REAL,
    date TEXT,
    merchant_name TEXT,
    category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT UNIQUE,
    original_amount REAL,
    adjusted_amount REAL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (transaction_id) REFERENCES transactions(id)
);
```

**Key functions:**
- `get_effective_amount(transaction_id)` - returns adjusted amount if exists, else original
- `get_spend_totals()` - returns dict with day/week/month totals using effective amounts
- `add_adjustment(transaction_id, new_amount, reason)`
- `find_transaction_by_merchant(merchant_name, date_hint=None)` - for agent lookups

---

### Phase 3: Plaid Integration

**Step 3.1: Create plaid_client.py**

- Initialize Plaid client with credentials
- Store access tokens in a simple JSON file or SQLite table

**Key functions:**
- `create_link_token()` - for initial account linking
- `exchange_public_token(public_token)` - after user links account
- `fetch_transactions(start_date, end_date)` - pull transactions
- `sync_new_transactions()` - incremental sync using Plaid's sync endpoint

**Step 3.2: Create simple link flow**

For initial setup, create a minimal HTML page that:
1. Loads Plaid Link
2. User connects accounts
3. Exchanges token and stores access token

---

### Phase 4: Web Dashboard

**Step 4.1: Create web_app.py**

Simple Flask app with one route:

- `GET /` - renders dashboard with current totals
- `GET /api/totals` - JSON endpoint for live updates

**Dashboard features:**
- Three big numbers: Today, This Week, This Month
- Auto-refresh every 30 seconds (simple JavaScript setInterval)
- Optional: recent transactions list

**Template (inline for simplicity):**
```html
<div class="totals">
  <div class="card">
    <h2>Today</h2>
    <p class="amount">${{ day }}</p>
  </div>
  <div class="card">
    <h2>This Week</h2>
    <p class="amount">${{ week }}</p>
  </div>
  <div class="card">
    <h2>This Month</h2>
    <p class="amount">${{ month }}</p>
  </div>
</div>
```

---

### Phase 5: LLM Agent

**Step 5.1: Create agent.py**

The agent interprets natural language and executes transaction adjustments.

**Agent capabilities:**
1. Parse user intent (adjust transaction, query spend, list recent)
2. Find matching transaction by merchant name and approximate date
3. Apply adjustment to database
4. Confirm action back to user

**Implementation approach:**
- Use Claude API with tool use
- Define tools:
  - `find_transaction(merchant_name, date_hint)` - searches DB
  - `adjust_transaction(transaction_id, new_amount, reason)` - applies override
  - `get_totals()` - returns current spend totals
  - `list_recent(n)` - shows last N transactions

**Example conversation:**
```
User: "Change the Applebee's transaction from yesterday to $60"
Agent: [calls find_transaction("Applebee's", "yesterday")]
       [finds transaction for $250]
       [calls adjust_transaction(tx_id, 60, "Split dinner with friends")]
       "Done! I adjusted the Applebee's transaction from $250 to $60. 
        Your new totals: Today $85, Week $340, Month $1,205"
```

---

### Phase 6: Telegram Bot

**Step 6.1: Create telegram_bot.py**

- Use python-telegram-bot library (async)
- Single handler for all messages → passes to agent
- Restrict to your chat ID only for security

**Key features:**
- `/start` - welcome message
- `/totals` - quick view of current spend
- `/recent` - list last 5 transactions
- Any other message → sent to LLM agent

**Security:**
```python
def restricted(func):
    async def wrapper(update, context):
        if str(update.effective_chat.id) != ALLOWED_CHAT_ID:
            return  # Silently ignore
        return await func(update, context)
    return wrapper
```

---

### Phase 7: Background Sync

**Step 7.1: Create sync_transactions.py**

Use APScheduler to periodically fetch new transactions:

```python
scheduler = BackgroundScheduler()
scheduler.add_job(sync_new_transactions, 'interval', minutes=15)
scheduler.start()
```

---

### Phase 8: Main Entry Point

**Step 8.1: Create run.py**

Combines all components:

```python
def main():
    # Initialize database
    init_db()
    
    # Start background sync
    start_scheduler()
    
    # Start Telegram bot in separate thread
    bot_thread = Thread(target=run_telegram_bot)
    bot_thread.start()
    
    # Start Flask web app (main thread)
    app.run(host='0.0.0.0', port=5000)
```

---

## Execution Instructions for Claude Code

When executing with Claude Code, follow this sequence:

1. **Create the project directory and all files**
2. **Set up the virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Create .env file** with user's API keys
4. **Initialize the database**
5. **Run the Plaid Link flow** to connect accounts (one-time setup)
6. **Start the application** with `python run.py`

---

## Testing Plan

1. **Plaid Sandbox Testing**
   - Use Plaid sandbox credentials first
   - Sandbox provides fake transactions for testing

2. **Agent Testing**
   - Test natural language parsing with various phrasings
   - Test edge cases: no matching transaction, ambiguous merchant names

3. **End-to-End Test**
   - Send Telegram message → verify adjustment in DB → verify dashboard updates

---

## Simplicity Decisions

To keep this simple for personal use:

1. **SQLite** instead of PostgreSQL - single file, no server
2. **Flask** instead of FastAPI - simpler for basic needs
3. **Inline templates** instead of Jinja files - fewer files
4. **Single run.py** entry point - easy to start/stop
5. **No authentication** on web UI - runs locally only
6. **Polling for updates** instead of webhooks - simpler setup
7. **Simple scheduler** instead of Celery - no Redis needed

---

## Notes for Claude Code Execution

- All API calls should have proper error handling
- Use logging throughout for debugging
- Store Plaid access tokens securely (encrypted at rest would be ideal, but for personal use, .env file is acceptable)
- The agent should handle ambiguous requests gracefully (ask for clarification)
- Dashboard should show "last synced" timestamp
- Consider adding a `/sync` command in Telegram to trigger manual sync