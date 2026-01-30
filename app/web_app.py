import logging
from flask import Flask, jsonify, request, render_template_string

from .config import WEB_HOST, WEB_PORT
from .database import get_spend_totals, get_recent_transactions
from .plaid_client import create_link_token, exchange_public_token, create_sandbox_token, load_access_tokens

logger = logging.getLogger(__name__)

app = Flask(__name__)

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spend Tracker</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #fff;
            padding: 20px;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-weight: 300;
            font-size: 2rem;
        }
        .totals {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .card {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 30px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.2s;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card h2 {
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            color: #888;
            margin-bottom: 15px;
        }
        .card .amount {
            font-size: 2.5rem;
            font-weight: 600;
            color: #4ade80;
        }
        .recent {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 20px;
        }
        .recent h2 {
            font-size: 1.2rem;
            margin-bottom: 20px;
            color: #888;
        }
        .transaction {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .transaction:last-child {
            border-bottom: none;
        }
        .transaction .merchant {
            font-weight: 500;
        }
        .transaction .date {
            font-size: 0.85rem;
            color: #888;
        }
        .transaction .amount {
            font-weight: 600;
            color: #f87171;
        }
        .transaction .adjusted {
            color: #fbbf24;
        }
        .sync-info {
            text-align: center;
            color: #666;
            font-size: 0.85rem;
            margin-top: 20px;
        }
        .link-section {
            text-align: center;
            margin: 30px 0;
        }
        .link-btn {
            background: #4ade80;
            color: #000;
            border: none;
            padding: 15px 30px;
            font-size: 1rem;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        }
        .link-btn:hover {
            background: #22c55e;
        }
        .no-accounts {
            text-align: center;
            padding: 40px;
            color: #888;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Spend Tracker</h1>

        {% if has_accounts %}
        <div class="totals">
            <div class="card">
                <h2>Today</h2>
                <p class="amount">${{ "%.2f"|format(day) }}</p>
            </div>
            <div class="card">
                <h2>This Week</h2>
                <p class="amount">${{ "%.2f"|format(week) }}</p>
            </div>
            <div class="card">
                <h2>This Month</h2>
                <p class="amount">${{ "%.2f"|format(month) }}</p>
            </div>
        </div>

        <div class="recent">
            <h2>Recent Transactions</h2>
            {% for txn in transactions %}
            <div class="transaction">
                <div>
                    <div class="merchant">{{ txn.merchant_name }}</div>
                    <div class="date">{{ txn.date }}</div>
                </div>
                <div class="amount {% if txn.adjusted_amount %}adjusted{% endif %}">
                    ${{ "%.2f"|format(txn.adjusted_amount if txn.adjusted_amount else txn.amount) }}
                    {% if txn.adjusted_amount %}*{% endif %}
                </div>
            </div>
            {% endfor %}
            {% if not transactions %}
            <p style="color: #888; text-align: center;">No transactions yet</p>
            {% endif %}
        </div>

        <p class="sync-info">Last synced: {{ last_synced or 'Never' }}</p>

        <div style="text-align: center; margin-top: 30px;">
            <button class="link-btn" style="background: #3b82f6;" onclick="linkAccount()">+ Add Another Account</button>
        </div>
        {% else %}
        <div class="no-accounts">
            <p>No bank accounts linked yet.</p>
            <div class="link-section">
                <button class="link-btn" onclick="linkAccount()">Link Bank Account</button>
                <p style="margin-top: 15px; color: #666;">Or for sandbox testing:</p>
                <button class="link-btn" style="background: #60a5fa; margin-top: 10px;" onclick="createSandbox()">Create Sandbox Account</button>
            </div>
        </div>
        {% endif %}
    </div>

    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <script>
        // Auto-refresh every 30 seconds
        {% if has_accounts %}
        setInterval(() => {
            fetch('/api/totals')
                .then(r => r.json())
                .then(data => {
                    document.querySelectorAll('.card .amount')[0].textContent = '$' + data.day.toFixed(2);
                    document.querySelectorAll('.card .amount')[1].textContent = '$' + data.week.toFixed(2);
                    document.querySelectorAll('.card .amount')[2].textContent = '$' + data.month.toFixed(2);
                });
        }, 30000);
        {% endif %}

        async function linkAccount() {
            const response = await fetch('/api/link-token');
            const { link_token } = await response.json();

            // Store link token for OAuth redirect flow
            localStorage.setItem('link_token', link_token);

            const handler = Plaid.create({
                token: link_token,
                onSuccess: async (public_token, metadata) => {
                    localStorage.removeItem('link_token');
                    await fetch('/api/exchange-token', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ public_token })
                    });
                    window.location.reload();
                },
                onExit: (err, metadata) => {
                    if (err) console.error('Plaid Link error:', JSON.stringify(err), 'metadata:', JSON.stringify(metadata));
                }
            });
            handler.open();
        }

        async function createSandbox() {
            const response = await fetch('/api/create-sandbox', { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                alert('Sandbox account created! Syncing transactions...');
                await fetch('/api/sync', { method: 'POST' });
                window.location.reload();
            } else {
                alert('Failed to create sandbox account: ' + data.error);
            }
        }

        // Handle OAuth redirect from institutions like Amex
        (function handleOAuthRedirect() {
            const params = new URLSearchParams(window.location.search);
            if (!params.has('oauth_state_id')) return;

            // Reuse the same link token from the original flow
            var linkToken = localStorage.getItem('link_token');
            if (!linkToken) {
                console.error('No link_token in localStorage for OAuth redirect');
                return;
            }

            var handler = Plaid.create({
                token: linkToken,
                receivedRedirectUri: window.location.href,
                onSuccess: function (public_token) {
                    localStorage.removeItem('link_token');
                    fetch('/api/exchange-token', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ public_token: public_token })
                    }).then(function () {
                        window.location.href = '/';
                    });
                },
                onExit: function (err, metadata) {
                    if (err) console.error('Plaid OAuth error:', JSON.stringify(err), 'metadata:', JSON.stringify(metadata));
                }
            });
            handler.open();
        })();
    </script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    """Render the main dashboard."""
    tokens = load_access_tokens()
    has_accounts = len(tokens) > 0

    totals = get_spend_totals()
    transactions = get_recent_transactions(10)

    return render_template_string(
        DASHBOARD_TEMPLATE,
        has_accounts=has_accounts,
        day=totals['day'],
        week=totals['week'],
        month=totals['month'],
        last_synced=totals.get('last_synced'),
        transactions=transactions
    )


@app.route('/api/totals')
def api_totals():
    """API endpoint for live spend totals."""
    totals = get_spend_totals()
    return jsonify(totals)


@app.route('/api/link-token')
def api_link_token():
    """Create a Plaid Link token."""
    link_token = create_link_token()
    if link_token:
        return jsonify({'link_token': link_token})
    return jsonify({'error': 'Failed to create link token'}), 500


@app.route('/api/exchange-token', methods=['POST'])
def api_exchange_token():
    """Exchange a public token for an access token."""
    data = request.json
    public_token = data.get('public_token')

    if not public_token:
        return jsonify({'error': 'Missing public_token'}), 400

    result = exchange_public_token(public_token)
    if result:
        # Trigger immediate sync after linking account
        from .plaid_client import sync_transactions
        logger.info("Triggering immediate sync after account link...")
        try:
            stats = sync_transactions()
            logger.info(f"Immediate sync complete: {stats}")
        except Exception as e:
            logger.error(f"Immediate sync failed: {e}")
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to exchange token'}), 500


@app.route('/api/create-sandbox', methods=['POST'])
def api_create_sandbox():
    """Create a sandbox access token for testing."""
    result = create_sandbox_token()
    if result:
        return jsonify({'success': True, 'item_id': result['item_id']})
    return jsonify({'success': False, 'error': 'Failed to create sandbox token'}), 500


@app.route('/api/sync', methods=['POST'])
def api_sync():
    """Trigger a manual sync."""
    from .plaid_client import sync_transactions
    stats = sync_transactions()
    return jsonify(stats)


@app.route('/api/recent')
def api_recent():
    """Get recent transactions."""
    transactions = get_recent_transactions(10)
    return jsonify(transactions)


@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Clear all transactions and sync state, then re-sync fresh."""
    from .database import get_connection
    from .plaid_client import sync_transactions

    conn = get_connection()
    cursor = conn.cursor()

    # Clear transactions and sync state
    cursor.execute("DELETE FROM transactions")
    cursor.execute("DELETE FROM adjustments")
    cursor.execute("DELETE FROM sync_state")
    conn.commit()
    conn.close()

    logger.info("Database cleared, starting fresh sync...")

    # Trigger fresh sync with new filters
    stats = sync_transactions()
    return jsonify({'success': True, 'cleared': True, 'sync_stats': stats})


def run_web_app():
    """Run the Flask web application."""
    logger.info(f"Starting web server on {WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False)
