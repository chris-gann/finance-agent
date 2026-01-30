import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Set

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode

from .config import PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ENV, ACCESS_TOKENS_PATH, PLAID_REDIRECT_URI
from .database import upsert_transaction, update_sync_state, get_sync_cursor

logger = logging.getLogger(__name__)

# Map environment string to Plaid Environment
ENV_MAP = {
    'sandbox': plaid.Environment.Sandbox,
    'development': plaid.Environment.Sandbox,  # Development uses Sandbox in newer SDK
    'production': plaid.Environment.Production,
}


def get_plaid_client():
    """Initialize and return Plaid API client."""
    configuration = plaid.Configuration(
        host=ENV_MAP.get(PLAID_ENV, plaid.Environment.Sandbox),
        api_key={
            'clientId': PLAID_CLIENT_ID,
            'secret': PLAID_SECRET,
        }
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


def load_access_tokens() -> list:
    """Load stored access tokens from JSON file."""
    try:
        with open(ACCESS_TOKENS_PATH, 'r') as f:
            data = json.load(f)
            return data.get('access_tokens', [])
    except FileNotFoundError:
        return []


def save_access_token(access_token: str, item_id: str):
    """Save a new access token to storage."""
    tokens = load_access_tokens()

    # Check if token already exists
    for token_data in tokens:
        if token_data.get('item_id') == item_id:
            token_data['access_token'] = access_token
            break
    else:
        tokens.append({
            'access_token': access_token,
            'item_id': item_id,
            'created_at': datetime.now().isoformat()
        })

    with open(ACCESS_TOKENS_PATH, 'w') as f:
        json.dump({'access_tokens': tokens}, f, indent=2)

    logger.info(f"Saved access token for item {item_id}")


def create_link_token() -> Optional[str]:
    """Create a Link token for Plaid Link initialization."""
    client = get_plaid_client()

    link_params = dict(
        user=LinkTokenCreateRequestUser(client_user_id="user-1"),
        client_name="Spend Tracker",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en"
    )
    if PLAID_REDIRECT_URI:
        link_params['redirect_uri'] = PLAID_REDIRECT_URI

    request = LinkTokenCreateRequest(**link_params)

    try:
        response = client.link_token_create(request)
        return response['link_token']
    except plaid.ApiException as e:
        error_response = json.loads(e.body)
        logger.error(f"Error creating link token: {error_response['error_code']}")
        return None


def exchange_public_token(public_token: str) -> Optional[dict]:
    """Exchange a public token for an access token."""
    client = get_plaid_client()

    request = ItemPublicTokenExchangeRequest(public_token=public_token)

    try:
        response = client.item_public_token_exchange(request)
        access_token = response['access_token']
        item_id = response['item_id']

        # Save the token
        save_access_token(access_token, item_id)

        return {
            'access_token': access_token,
            'item_id': item_id
        }
    except plaid.ApiException as e:
        error_response = json.loads(e.body)
        logger.error(f"Error exchanging token: {error_response['error_code']}")
        return None


def create_sandbox_token() -> Optional[dict]:
    """Create a sandbox access token for testing (sandbox only)."""
    if PLAID_ENV != 'sandbox':
        logger.error("Sandbox token creation only available in sandbox environment")
        return None

    client = get_plaid_client()

    # Create sandbox public token
    request = SandboxPublicTokenCreateRequest(
        institution_id='ins_109508',  # First Platypus Bank
        initial_products=[Products('transactions')]
    )

    try:
        response = client.sandbox_public_token_create(request)
        public_token = response['public_token']

        # Exchange for access token
        return exchange_public_token(public_token)
    except plaid.ApiException as e:
        error_response = json.loads(e.body)
        logger.error(f"Error creating sandbox token: {error_response['error_code']}")
        return None


def get_checking_account_ids(access_token: str) -> Set[str]:
    """Get account IDs for checking accounts only."""
    client = get_plaid_client()

    try:
        request = AccountsGetRequest(access_token=access_token)
        response = client.accounts_get(request)

        checking_ids = set()
        for account in response['accounts']:
            # Log all accounts for debugging
            subtype = str(account['subtype']) if account['subtype'] else 'None'
            logger.info(f"Found account: {account['name']} | type={account['type']} | subtype={subtype}")

            # Filter for checking accounts only (handle both string and enum)
            if subtype.lower() == 'checking':
                checking_ids.add(account['account_id'])
                logger.info(f"  -> Including as checking account")

        return checking_ids
    except plaid.ApiException as e:
        error_response = json.loads(e.body)
        logger.error(f"Error fetching accounts: {error_response['error_code']}")
        return set()


def sync_transactions() -> dict:
    """Sync transactions from checking accounts only (spending only, no deposits)."""
    client = get_plaid_client()
    access_tokens = load_access_tokens()

    if not access_tokens:
        logger.warning("No access tokens found. Please link an account first.")
        return {'added': 0, 'modified': 0, 'removed': 0}

    stats = {'added': 0, 'modified': 0, 'removed': 0, 'skipped_deposits': 0, 'skipped_non_checking': 0}
    cursor = get_sync_cursor()

    for token_data in access_tokens:
        access_token = token_data['access_token']

        # Get checking account IDs for this token
        checking_account_ids = get_checking_account_ids(access_token)
        if not checking_account_ids:
            logger.warning("No checking accounts found for this token")

        try:
            # Initial sync request
            request = TransactionsSyncRequest(
                access_token=access_token,
                cursor=cursor
            ) if cursor else TransactionsSyncRequest(access_token=access_token)

            response = client.transactions_sync(request)

            # Process added transactions
            for txn in response['added']:
                # Skip pending transactions
                if txn['pending']:
                    continue
                # Skip non-checking accounts
                if checking_account_ids and txn['account_id'] not in checking_account_ids:
                    stats['skipped_non_checking'] += 1
                    continue
                # Skip deposits (negative amounts = money coming in)
                if txn['amount'] <= 0:
                    stats['skipped_deposits'] += 1
                    continue

                upsert_transaction(
                    transaction_id=txn['transaction_id'],
                    account_id=txn['account_id'],
                    amount=txn['amount'],
                    date=str(txn['date']),
                    merchant_name=txn['merchant_name'] or txn['name'] or 'Unknown',
                    category=txn['category'][0] if txn['category'] else 'Uncategorized'
                )
                stats['added'] += 1

            stats['modified'] += len(response['modified'])
            stats['removed'] += len(response['removed'])

            # Paginate through all results
            while response['has_more']:
                request = TransactionsSyncRequest(
                    access_token=access_token,
                    cursor=response['next_cursor']
                )
                response = client.transactions_sync(request)

                for txn in response['added']:
                    if txn['pending']:
                        continue
                    if checking_account_ids and txn['account_id'] not in checking_account_ids:
                        stats['skipped_non_checking'] += 1
                        continue
                    if txn['amount'] <= 0:
                        stats['skipped_deposits'] += 1
                        continue

                    upsert_transaction(
                        transaction_id=txn['transaction_id'],
                        account_id=txn['account_id'],
                        amount=txn['amount'],
                        date=str(txn['date']),
                        merchant_name=txn['merchant_name'] or txn['name'] or 'Unknown',
                        category=txn['category'][0] if txn['category'] else 'Uncategorized'
                    )
                    stats['added'] += 1

                stats['modified'] += len(response['modified'])
                stats['removed'] += len(response['removed'])

            # Save the cursor for incremental sync
            update_sync_state(response['next_cursor'])

        except plaid.ApiException as e:
            error_response = json.loads(e.body)
            logger.error(f"Error syncing transactions: {error_response['error_code']}")

    logger.info(f"Sync complete: {stats}")
    return stats
