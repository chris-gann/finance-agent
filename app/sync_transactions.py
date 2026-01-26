import logging
from apscheduler.schedulers.background import BackgroundScheduler

from .config import SYNC_INTERVAL_MINUTES
from .plaid_client import sync_transactions, load_access_tokens

logger = logging.getLogger(__name__)

scheduler = None


def sync_job():
    """Background job to sync transactions from Plaid."""
    tokens = load_access_tokens()
    if not tokens:
        logger.debug("No access tokens configured, skipping sync")
        return

    logger.info("Running scheduled transaction sync...")
    try:
        stats = sync_transactions()
        logger.info(f"Sync complete: added={stats['added']}, modified={stats['modified']}, removed={stats['removed']}")
    except Exception as e:
        logger.error(f"Scheduled sync failed: {e}")


def start_scheduler():
    """Start the background scheduler for periodic syncs."""
    global scheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        sync_job,
        'interval',
        minutes=SYNC_INTERVAL_MINUTES,
        id='transaction_sync',
        replace_existing=True
    )
    scheduler.start()
    logger.info(f"Background scheduler started (sync every {SYNC_INTERVAL_MINUTES} minutes)")


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        logger.info("Background scheduler stopped")
