#!/usr/bin/env python3
"""
Personal Spend Tracker - Main Entry Point

This application combines:
1. Plaid integration for fetching bank transactions
2. A local web dashboard showing spend totals
3. A Telegram bot with AI agent for natural language commands
"""

import logging
import signal
import sys
import asyncio
from threading import Thread

from app.database import init_db
from app.sync_transactions import start_scheduler, stop_scheduler
from app.telegram_bot import create_telegram_app
from app.web_app import run_web_app
from app.plaid_client import sync_transactions, load_access_tokens
from app.config import WEB_PORT

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutting down...")
    stop_scheduler()
    sys.exit(0)


def run_telegram_in_thread():
    """Run the Telegram bot in its own thread with event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = create_telegram_app()
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling())

    # Keep the loop running
    try:
        loop.run_forever()
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")
    finally:
        loop.run_until_complete(app.updater.stop())
        loop.run_until_complete(app.stop())
        loop.run_until_complete(app.shutdown())
        loop.close()


def main():
    """Main entry point for the application."""
    print(f"""
    ╔═══════════════════════════════════════╗
    ║       Personal Spend Tracker          ║
    ╠═══════════════════════════════════════╣
    ║  Web Dashboard: http://localhost:{WEB_PORT:<5}║
    ║  Telegram Bot:  Active                ║
    ╚═══════════════════════════════════════╝
    """)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize database
    logger.info("Initializing database...")
    init_db()

    # Check for linked accounts
    tokens = load_access_tokens()
    if tokens:
        logger.info(f"Found {len(tokens)} linked account(s)")
        # Do initial sync
        logger.info("Running initial transaction sync...")
        stats = sync_transactions()
        logger.info(f"Initial sync: {stats['added']} transactions added")
    else:
        logger.info(f"No linked accounts. Visit http://localhost:{WEB_PORT} to link your bank account.")

    # Start background scheduler
    start_scheduler()

    # Start Telegram bot in separate thread
    logger.info("Starting Telegram bot...")
    telegram_thread = Thread(target=run_telegram_in_thread, daemon=True)
    telegram_thread.start()

    # Start Flask web app (main thread - blocking)
    logger.info("Starting web dashboard...")
    run_web_app()


if __name__ == '__main__':
    main()
