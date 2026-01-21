import json
import logging
from typing import Optional
from anthropic import Anthropic

from config import ANTHROPIC_API_KEY
from database import (
    find_transaction_by_merchant,
    add_adjustment,
    get_spend_totals,
    get_recent_transactions,
    get_transaction_by_id
)
from plaid_client import sync_transactions

logger = logging.getLogger(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)

TOOLS = [
    {
        "name": "find_transaction",
        "description": "Search for transactions by merchant name. Optionally filter by date. Returns matching transactions with their IDs, amounts, dates, and merchant names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "merchant_name": {
                    "type": "string",
                    "description": "The merchant name to search for (partial match supported)"
                },
                "date_hint": {
                    "type": "string",
                    "description": "Optional date hint like 'yesterday', 'today', 'last week', or a date in YYYY-MM-DD format"
                }
            },
            "required": ["merchant_name"]
        }
    },
    {
        "name": "adjust_transaction",
        "description": "Adjust the amount of a transaction. Use this when the user wants to change a transaction amount (e.g., for split bills, reimbursements, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "transaction_id": {
                    "type": "string",
                    "description": "The unique ID of the transaction to adjust"
                },
                "new_amount": {
                    "type": "number",
                    "description": "The new amount for the transaction"
                },
                "reason": {
                    "type": "string",
                    "description": "The reason for the adjustment (e.g., 'Split dinner with friends')"
                }
            },
            "required": ["transaction_id", "new_amount", "reason"]
        }
    },
    {
        "name": "get_totals",
        "description": "Get current spending totals for today, this week, and this month",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_recent",
        "description": "List the most recent transactions",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of recent transactions to retrieve (default: 5, max: 20)"
                }
            }
        }
    },
    {
        "name": "sync_now",
        "description": "Trigger an immediate sync of transactions from Plaid",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

SYSTEM_PROMPT = """You are a helpful personal finance assistant. You help users track and manage their spending by:

1. Looking up transactions by merchant name
2. Adjusting transaction amounts (for split bills, reimbursements, etc.)
3. Showing spending totals for today, this week, and this month
4. Listing recent transactions
5. Syncing new transactions from bank accounts

When a user asks to adjust a transaction:
- First use find_transaction to locate the transaction
- If multiple matches are found, ask the user to clarify which one
- Then use adjust_transaction with the transaction ID

Always be concise and helpful. After making adjustments, show the updated totals.

If a user's request is ambiguous, ask for clarification rather than guessing."""


def process_tool_call(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "find_transaction":
            merchant = tool_input.get("merchant_name")
            date_hint = tool_input.get("date_hint")
            results = find_transaction_by_merchant(merchant, date_hint)

            if not results:
                return f"No transactions found for '{merchant}'"

            output = []
            for txn in results:
                effective_amount = txn['adjusted_amount'] if txn['adjusted_amount'] else txn['amount']
                adj_note = " (adjusted)" if txn['adjusted_amount'] else ""
                output.append(
                    f"- ID: {txn['id']}\n"
                    f"  Merchant: {txn['merchant_name']}\n"
                    f"  Amount: ${effective_amount:.2f}{adj_note}\n"
                    f"  Date: {txn['date']}"
                )
            return f"Found {len(results)} transaction(s):\n" + "\n".join(output)

        elif tool_name == "adjust_transaction":
            txn_id = tool_input.get("transaction_id")
            new_amount = tool_input.get("new_amount")
            reason = tool_input.get("reason", "User adjustment")

            # Get original transaction for reference
            txn = get_transaction_by_id(txn_id)
            if not txn:
                return f"Transaction {txn_id} not found"

            original = txn['amount']
            success = add_adjustment(txn_id, new_amount, reason)

            if success:
                return (f"Adjusted transaction at {txn['merchant_name']}:\n"
                       f"Original: ${original:.2f} -> New: ${new_amount:.2f}\n"
                       f"Reason: {reason}")
            else:
                return "Failed to adjust transaction"

        elif tool_name == "get_totals":
            totals = get_spend_totals()
            last_sync = totals.get('last_synced', 'Never')
            return (f"Spending Totals:\n"
                   f"Today: ${totals['day']:.2f}\n"
                   f"This Week: ${totals['week']:.2f}\n"
                   f"This Month: ${totals['month']:.2f}\n"
                   f"Last synced: {last_sync}")

        elif tool_name == "list_recent":
            count = min(tool_input.get("count", 5), 20)
            transactions = get_recent_transactions(count)

            if not transactions:
                return "No recent transactions found"

            output = []
            for txn in transactions:
                effective_amount = txn['adjusted_amount'] if txn['adjusted_amount'] else txn['amount']
                adj_note = " (adjusted)" if txn['adjusted_amount'] else ""
                output.append(
                    f"- {txn['merchant_name']}: ${effective_amount:.2f}{adj_note} on {txn['date']}"
                )
            return "Recent transactions:\n" + "\n".join(output)

        elif tool_name == "sync_now":
            stats = sync_transactions()
            return (f"Sync complete!\n"
                   f"Added: {stats['added']} transactions\n"
                   f"Modified: {stats['modified']}\n"
                   f"Removed: {stats['removed']}")

        else:
            return f"Unknown tool: {tool_name}"

    except Exception as e:
        logger.error(f"Error processing tool {tool_name}: {e}")
        return f"Error executing {tool_name}: {str(e)}"


def run_agent(user_message: str) -> str:
    """Process a user message through the agent and return the response."""
    messages = [{"role": "user", "content": user_message}]

    max_iterations = 10  # Prevent infinite loops

    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        # Add assistant response to messages
        messages.append({"role": "assistant", "content": response.content})

        # Check if Claude wants to use a tool
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    logger.info(f"Agent calling tool: {tool_name}")
                    tool_result = process_tool_call(tool_name, tool_input)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_result
                    })

            # Add tool results to messages
            messages.append({"role": "user", "content": tool_results})
        else:
            # No tool use, extract final text response
            for block in response.content:
                if hasattr(block, 'text'):
                    return block.text
            return "I'm sorry, I couldn't process that request."

    return "I'm sorry, I took too many steps trying to complete that request."
