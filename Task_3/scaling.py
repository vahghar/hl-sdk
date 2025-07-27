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
    eth_price = Decimal(mids["ETH"])

    entry_price = api.universe.round_price("ETH", eth_price * Decimal("0.999"))
    tp_price = api.universe.round_price("ETH", eth_price * Decimal("1.015"))
    sl_price = api.universe.round_price("ETH", eth_price * Decimal("0.985"))
    size = Decimal("0.005")

    print(f"[Account {index}] Entry @ {entry_price}, TP @ {tp_price}, SL @ {sl_price}")

    async with api.ws.run():
        res = await api.exchange.place_order(
            asset="ETH", is_buy=True, size=size,
            limit_price=entry_price, order_type=LIMIT_GTC,
            reduce_only=False
        )
        if not res.is_ok():
            print(f"[Account {index}] Entry failed:", res.unwrap_err())
            return

        statuses = res.unwrap()["response"]["data"]["statuses"]
        entry_oid = None
        filled_immediately = False

        for status in statuses:
            if is_resting_status(status):
                entry_oid = status["resting"]["oid"]
                print(f"[Account {index}] Order is resting. OID: {entry_oid}")
            elif is_filled_status(status):
                fill = status["filled"]
                print(f"[Account {index}] Filled instantly: {fill['totalSz']} @ {fill['avgPx']}")
                entry_oid = fill["oid"]
                filled_immediately = True
                break
            elif is_error_status(status):
                print(f"[Account {index}] Order error: {status['error']}")
                return

        if not entry_oid:
            print(f"[Account {index}] Could not retrieve entry order ID.")
            return

        if not filled_immediately:
            print(f"[Account {index}] Waiting for fill via WebSocket... (30s max)")
            filled = False
            try:
                sub_id, queue = await api.ws.subscriptions.order_updates()

                for _ in range(30):
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                        updates = msg["data"]

                        for update in updates:
                            order = update["order"]
                            if order["oid"] == entry_oid and update["status"] == "filled":
                                print(f"[Account {index}] Order filled via WebSocket.")
                                filled = True
                                break
                        if filled:
                            break
                    except asyncio.TimeoutError:
                        continue

                await api.ws.subscriptions.unsubscribe(sub_id)

                if not filled:
                    print(f"[Account {index}] Not filled in 30s. Canceling...")
                    cancel_result = await api.exchange.cancel_order(asset="ETH", order_id=entry_oid)
                    if cancel_result.is_ok():
                        print(f"[Account {index}] Canceled successfully.")
                    else:
                        print(f"[Account {index}] Cancel failed: {cancel_result.unwrap_err()}")
                    return

            except Exception as e:
                print(f"[Account {index}] WebSocket error: {e}")
                return

        tp_res = await api.exchange.place_order(
            asset="ETH", is_buy=False, size=size,
            limit_price=tp_price, order_type=LIMIT_GTC,
            reduce_only=True
        )
        print(f"[Account {index}] TP Order: {tp_res}")

        sl_res = await api.exchange.place_order(
            asset="ETH", is_buy=False, size=size,
            limit_price=sl_price, order_type=LIMIT_GTC,
            reduce_only=True
        )
        print(f"[Account {index}] SL Order: {sl_res}")

async def main():
    await asyncio.gather(*[run_for_account(i) for i in range(1, NUM_ACCOUNTS + 1)])

if __name__ == "__main__":
    asyncio.run(main())
