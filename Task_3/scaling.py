import os
from decimal import Decimal
from dotenv import load_dotenv
from hl import LIMIT_GTC, TESTNET, Account, Api
from hl.types import is_error_status, is_filled_status, is_resting_status
import asyncio

load_dotenv()

NUM_ACCOUNTS = 5

async def run_for_account(index: int):
    address = os.environ[f"HL_ADDRESS_{index}"]
    secret_key = os.environ[f"HL_SECRET_KEY_{index}"]
    account = Account(address=address, secret_key=secret_key)
    api = await Api.create(account=account, network=TESTNET)

    mids_result = await api.info.all_mids()
    if mids_result.is_err():
        print(f"[Account {index}] Error getting prices: {mids_result.unwrap_err()}")
        return

    mids = mids_result.unwrap()
    btc_price = Decimal(mids["BTC"])

    # -- Price Logic --
    ENTRY_OFFSET = Decimal("0.99")
    TP_OFFSET = Decimal("1.02")
    SL_OFFSET = Decimal("0.98")
    SIZE = Decimal("0.0005")

    entry_price = api.universe.round_price("BTC", btc_price * ENTRY_OFFSET)
    tp_price    = api.universe.round_price("BTC", btc_price * TP_OFFSET)
    sl_price    = api.universe.round_price("BTC", btc_price * SL_OFFSET)

    print(f"[Account {index}] Entry @ {entry_price}, TP @ {tp_price}, SL @ {sl_price}")

    # -- Place Entry Order --
    res = await api.exchange.place_order(
        asset="BTC", is_buy=True, size=SIZE,
        limit_price=entry_price, order_type=LIMIT_GTC,
        reduce_only=False
    )
    if not res.is_ok():
        print(f"[Account {index}] Entry failed:", res.unwrap_err())
        return

    statuses = res.unwrap()["response"]["data"]["statuses"]
    entry_oid = None

    for status in statuses:
        if is_resting_status(status):
            entry_oid = status["resting"]["oid"]
            print(f"[Account {index}] Order is resting. OID: {entry_oid}")
        elif is_filled_status(status):
            fill = status["filled"]
            print(f"[Account {index}] Filled instantly: {fill['totalSz']} @ {fill['avgPx']}")
            entry_oid = fill["oid"]
            break
        elif is_error_status(status):
            print(f"[Account {index}] Order error: {status['error']}")
            return

    if not entry_oid:
        print(f"[Account {index}] Could not retrieve entry order ID.")
        return

    # -- Polling Skipped (No order_status function) --
    # Assume order is resting or filled instantly. If resting, you may wait and query open orders if SDK supports.

    # -- Place TP Order --
    tp_res = await api.exchange.place_order(
        asset="BTC", is_buy=False, size=SIZE,
        limit_price=tp_price, order_type=LIMIT_GTC,
        reduce_only=True
    )
    print(f"[Account {index}] TP Order: {tp_res}")

    # -- Place SL Order --
    sl_res = await api.exchange.place_order(
        asset="BTC", is_buy=False, size=SIZE,
        limit_price=sl_price, order_type=LIMIT_GTC,
        reduce_only=True
    )
    print(f"[Account {index}] SL Order: {sl_res}")

async def main():
    await asyncio.gather(*[run_for_account(i) for i in range(1, NUM_ACCOUNTS + 1)])

if __name__ == "__main__":
    asyncio.run(main())
