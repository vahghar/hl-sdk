import os
import re
import asyncio
from decimal import Decimal
from dotenv import load_dotenv
from hl import LIMIT_GTC, TESTNET, Account, Api
from hl.types import is_error_status, is_filled_status, is_resting_status

load_dotenv()

class CommandParser:
    BUY_RE = re.compile(
        r"buy\s+(?P<qty>[0-9]+(?:\.[0-9]+)?)\s+(?P<symbol>\w+)(?:\s+at\s+(?P<price>[0-9]+(?:\.[0-9]+)?|market))?",
        re.IGNORECASE,
    )
    SELL_RE = re.compile(
        r"sell\s+(?P<qty>[0-9]+(?:\.[0-9]+)?)\s+(?P<symbol>\w+)(?:\s+at\s+(?P<price>[0-9]+(?:\.[0-9]+)?|market))?",
        re.IGNORECASE,
    )
    ALL_RE = re.compile(r"sell\s+all\s+(?P<symbol>\w+)", re.IGNORECASE)
    CANCEL_RE = re.compile(r"cancel\s+(?P<oid>\w+)", re.IGNORECASE)

    @classmethod
    def parse(cls, text: str):
        text = text.strip()
        for cmd_type, pattern in [("buy", cls.BUY_RE), ("sell", cls.SELL_RE)]:
            m = pattern.match(text)
            if m:
                qty = Decimal(m.group("qty"))
                symbol = m.group("symbol").upper()
                price_str = m.group("price")
                price = None if price_str and price_str.lower() == "market" else (Decimal(price_str) if price_str else None)
                return cmd_type, symbol, qty, price
        return None, None, None, None

async def get_market_data(api, symbol):
    mids_result = await api.info.all_mids()
    if mids_result.is_err():
        print(f"[MarketData] Error getting prices: {mids_result.unwrap_err()}")
        return
    mids = mids_result.unwrap()
    price = Decimal(mids.get(symbol, 0))
    print(f"[MarketData] {symbol} mid price: {price}")

async def show_portfolio(api):
    result = await api.info.user_state()
    if result.is_err():
        print("[Portfolio] Error fetching portfolio")
        return
    data = result.unwrap()
    positions = data.get("assetPositions", [])
    print("\n--- Portfolio ---")
    if not positions:
        print("No open positions")
    else:
        for pos in positions:
            pos_data = pos.get("position", {})
            size = Decimal(pos_data.get("szi", "0"))
            if size != 0:
                coin = pos_data.get("coin", "Unknown")
                entry = Decimal(pos_data.get("entryPx", "0"))
                unrealized_pnl = Decimal(pos_data.get("unrealizedPnl", "0"))
                print(f"{coin}: {size} units @ entry ${entry} | PnL: ${unrealized_pnl}")
    print("------------------\n")

async def show_balances(api):
    print("\n=== Account Balances ===")
    perp_result = await api.info.user_state()
    if perp_result.is_ok():
        perp = perp_result.unwrap()
        print("\n📊 Perpetual Account:")
        print(f"  Total Value: ${perp.get('marginSummary', {}).get('accountValue', 'N/A')}")
        print(f"  Withdrawable: ${perp.get('withdrawable', 'N/A')}")
        print(f"  Cross Margin Used: ${perp.get('crossMarginSummary', {}).get('totalMarginUsed', 'N/A')}")
        print(f"  Cross Maintenance Margin: ${perp.get('crossMarginSummary', {}).get('totalNtlPos', 'N/A')}")
    else:
        print(f"[Error] Failed to get perpetual balance: {perp_result.unwrap_err()}")

    spot_result = await api.info.spot_user_state()
    if spot_result.is_ok():
        spot = spot_result.unwrap()
        print("\n💰 Spot Account:")
        total_usd_value = Decimal("0")
        mids_result = await api.info.all_mids()
        mids = mids_result.unwrap() if mids_result.is_ok() else {}
        balances = spot.get("balances", [])
        if balances:
            for balance in balances:
                coin = balance.get("coin", "Unknown")
                total = Decimal(balance.get("total", "0"))
                hold = Decimal(balance.get("hold", "0"))
                available = total - hold
                if total > 0:
                    print(f"  {coin}: {total} total, {available} available")
                    if coin == "USDC":
                        total_usd_value += total
                    elif coin in mids:
                        price = Decimal(mids[coin])
                        usd_value = total * price
                        total_usd_value += usd_value
                        print(f"     ≈ ${usd_value:.2f} (@ ${price})")
            print(f"\n  Total USD Value: ≈ ${total_usd_value:.2f}")
        else:
            print("  No spot balances.")
    else:
        print(f"[Error] Failed to get spot balance: {spot_result.unwrap_err()}")
    print("\n========================\n")

async def run_nlp_bot():
    index = 2
    address = os.getenv(f"HL_ADDRESS_{index}")
    secret_key = os.getenv(f"HL_SECRET_KEY_{index}")
    if not address or not secret_key:
        print(f"Missing environment variables HL_ADDRESS_{index} or HL_SECRET_KEY_{index}")
        return
    account = Account(address=address, secret_key=secret_key)
    api = await Api.create(account=account, network=TESTNET)
    print("[Bot] Connected to Hyperliquid TESTNET as account", address)

    print("Enter commands: 'buy/sell <qty> <symbol> [at <price>|market]', 'sell all <symbol>', 'cancel <order_id>', 'balances', 'portfolio', 'price <symbol>', or 'exit'")
    while True:
        text = input(">> ").strip()
        if text.lower() in ("exit", "quit"):
            print("Exiting bot.")
            break
        if text.lower().startswith("price "):
            _, symbol = text.split(maxsplit=1)
            await get_market_data(api, symbol.upper())
            continue
        if text.lower() == "portfolio":
            await show_portfolio(api)
            continue
        if text.lower() == "balances":
            await show_balances(api)
            continue
        if text.lower() == "help":
            print("""
• buy <qty> <sym> [at <price>]
• sell <qty> <sym> [at <price>]
• sell all <sym>
• cancel <order_id>
• balances
• portfolio
• price <sym>
• exit
""")
            continue

        m_cancel = CommandParser.CANCEL_RE.match(text)
        if m_cancel:
            oid = m_cancel.group("oid")
            cancel_res = await api.exchange.cancel_order(oid=oid)
            if cancel_res.is_ok():
                print(f"Canceled order {oid}")
            else:
                print(f"Cancel failed: {cancel_res.unwrap_err()}")
            continue

        m_all = CommandParser.ALL_RE.match(text)
        if m_all:
            sym = m_all.group("symbol").upper()
            spot_state = (await api.info.spot_user_state()).unwrap()
            bal = next((b for b in spot_state.get("balances", []) if b.get("coin") == sym), None)
            if not bal:
                print(f"No balance info for {sym}")
                continue
            total = Decimal(bal.get("total", "0"))
            hold = Decimal(bal.get("hold", "0"))
            qty = total - hold
            if qty <= 0:
                print(f"Nothing to sell for {sym}")
                continue
            print(f"Selling all {qty} {sym} at market")
            res = await api.exchange.place_order(
                asset=sym,
                is_buy=False,
                size=qty,
                limit_price=None,
                order_type=None,
                reduce_only=False,
            )
            if not res.is_ok():
                print(f"Sell all failed: {res.unwrap_err()}")
            else:
                print(f"Sell all order placed for {sym}, qty {qty}")
            continue

        cmd, symbol, qty, price = CommandParser.parse(text)
        if not cmd:
            print("Unrecognized command. Try 'buy 0.1 BTC at 30000', 'sell all BTC', or 'cancel <id>'.")
            continue
        order_type = LIMIT_GTC if price is not None else None
        try:
            res = await api.exchange.place_order(
                asset=symbol,
                is_buy=(cmd == "buy"),
                size=qty,
                limit_price=price,
                order_type=order_type,
                reduce_only=(cmd == "sell"),
            )
        except Exception as e:
            print(f"[Error] API call failed: {e}")
            continue
        if not res.is_ok():
            print(f"[Error] Order failed: {res.unwrap_err()}")
            continue
        statuses = res.unwrap()["response"]["data"]["statuses"]
        for status in statuses:
            if is_resting_status(status):
                oid = status["resting"]["oid"]
                print(f"Order resting. OID: {oid}")
            elif is_filled_status(status):
                fill = status["filled"]
                print(f"Filled: {fill['totalSz']} @ {fill['avgPx']}")
            elif is_error_status(status):
                print(f"Order error: {status['error']}")

async def main():
    await run_nlp_bot()

if __name__ == "__main__":
    asyncio.run(main())
