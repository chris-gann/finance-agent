import logging
from functools import wraps

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import get_spend_totals, get_recent_transactions
from agent import run_agent
from plaid_client import sync_transactions

logger = logging.getLogger(__name__)


def restricted(func):
    """Decorator to restrict bot access to allowed chat ID only."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        if chat_id != TELEGRAM_CHAT_ID:
            logger.warning(f"Unauthorized access attempt from chat_id: {chat_id}")
            return
        return await func(update, context)
    return wrapper


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    welcome_message = (
        "Welcome to your Spend Tracker Bot!\n\n"
        "I can help you track and manage your spending. Try:\n"
        "- /totals - View spending totals\n"
        "- /recent - See recent transactions\n"
        "- /sync - Sync new transactions\n\n"
        "Or just ask me anything like:\n"
        "- 'Change the Starbucks transaction to $5'\n"
        "- 'How much have I spent this week?'\n"
        "- 'Show me my recent purchases'"
    )
    await update.message.reply_text(welcome_message)


@restricted
async def totals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /totals command - show spending totals."""
    try:
        spending = get_spend_totals()
        last_sync = spending.get('last_synced', 'Never')

        message = (
            f"Spending Totals\n"
            f"{'─' * 20}\n"
            f"Today: ${spending['day']:.2f}\n"
            f"This Week: ${spending['week']:.2f}\n"
            f"This Month: ${spending['month']:.2f}\n"
            f"{'─' * 20}\n"
            f"Last synced: {last_sync}"
        )
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Error getting totals: {e}")
        await update.message.reply_text("Sorry, couldn't fetch spending totals.")


@restricted
async def recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /recent command - show recent transactions."""
    try:
        transactions = get_recent_transactions(5)

        if not transactions:
            await update.message.reply_text("No recent transactions found.")
            return

        lines = ["Recent Transactions", "─" * 25]
        for txn in transactions:
            amount = txn['adjusted_amount'] if txn['adjusted_amount'] else txn['amount']
            adj_marker = "*" if txn['adjusted_amount'] else ""
            lines.append(f"{txn['date']} | {txn['merchant_name'][:15]:<15} | ${amount:.2f}{adj_marker}")

        lines.append("─" * 25)
        lines.append("* = adjusted amount")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"Error getting recent transactions: {e}")
        await update.message.reply_text("Sorry, couldn't fetch recent transactions.")


@restricted
async def sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sync command - trigger manual sync."""
    await update.message.reply_text("Syncing transactions...")
    try:
        stats = sync_transactions()
        message = (
            f"Sync complete!\n"
            f"Added: {stats['added']} transactions\n"
            f"Modified: {stats['modified']}\n"
            f"Removed: {stats['removed']}"
        )
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Error syncing: {e}")
        await update.message.reply_text("Sorry, sync failed. Please try again later.")


@restricted
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language messages through the agent."""
    user_message = update.message.text
    logger.info(f"Received message: {user_message}")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )

    try:
        response = run_agent(user_message)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text(
            "Sorry, I encountered an error processing your request. Please try again."
        )


def create_telegram_app() -> Application:
    """Create and configure the Telegram application."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("totals", totals))
    application.add_handler(CommandHandler("recent", recent))
    application.add_handler(CommandHandler("sync", sync))

    # Add message handler for natural language (non-command messages)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return application


def run_telegram_bot():
    """Run the Telegram bot (blocking)."""
    logger.info("Starting Telegram bot...")
    app = create_telegram_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_telegram_bot_async():
    """Run the Telegram bot asynchronously."""
    logger.info("Starting Telegram bot (async)...")
    app = create_telegram_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    return app
