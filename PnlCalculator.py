import json
from example_utils import setup, setup_fees
from hyperliquid.utils import constants
from datetime import datetime

class PnLCalculator:
    """
    PnLCalculator uses the latest Spot and Perp orderbooks from HyperLiquid to
    calculate the pnl if we close short and sell spots at the market price.

    Closing short uses taker fee, whereas selling spot uses maker fee.
    """
    def __init__(self, base_url=constants.MAINNET_API_URL):
        self.address, self.info, self.exchange = setup(base_url=base_url, skip_ws=True)
        self.taker_fee, self.maker_fee = setup_fees()
        print(f"Taker Fee: {self.taker_fee}, Maker Fee: {self.maker_fee}")

    def calculate_perp_pnl(self, l2_snapshot, position_size, entry_price, position_type="short"):
        if position_type not in ["short", "long"]:
            return {"error": "Invalid position_type. Use 'short' or 'long'."}
        
        if position_type == "short":
            orders = l2_snapshot['levels'][1]
        else:
            orders = l2_snapshot['levels'][0]

        remaining_size = position_size
        total_cost = 0.0
        total_executed = 0.0

        for order in orders:
            px = float(order['px'])
            sz = float(order['sz'])
            
            if remaining_size <= 0:
                break
            
            size_to_execute = min(remaining_size, sz)
            total_cost += size_to_execute * px
            total_executed += size_to_execute
            remaining_size -= size_to_execute

        if total_executed == 0:
            return {"error": "No liquidity in the order book"}
        
        avg_execution_price = total_cost / total_executed
        
        if position_type == "short":
            pnl_before_fees = (entry_price - avg_execution_price) * position_size
        else:
            pnl_before_fees = (avg_execution_price - entry_price) * position_size

        # Apply taker fee to the total cost
        fee = total_cost * self.taker_fee
        pnl = pnl_before_fees - fee

        timestamp = l2_snapshot['time']
        human_readable_time = datetime.fromtimestamp(timestamp=timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')

        return {
            "position_type": position_type,
            "entry_price": entry_price,
            "execution_price": avg_execution_price,
            "position_size": position_size,
            "fee": fee,
            "pnl": pnl,
            "timestamp": timestamp,
            "human": human_readable_time
        }

    def extract_entry_price_and_size(self, user_state, coin_name):
        positions = user_state.get("assetPositions", [])
        
        for item in positions:
            position = item.get("position", {})
            coin = position.get("coin", "Unknown")
            
            if coin == coin_name:
                entry_px = position.get("entryPx", None)
                size = position.get("szi", None)
                
                entry_px = float(entry_px) if entry_px is not None else None
                size = float(size) if size is not None else None
                
                if size is not None and size < 0:
                    size = abs(size)
                
                return entry_px, size
        
        return None, None

    def calculate_spot_pnl(self, l2_snapshot, position_size, entry_price):
        bids = l2_snapshot['levels'][0]

        if not bids:
            return {"error": "No liquidity in the order book"}

        remaining_size = position_size
        total_revenue = 0.0
        total_executed = 0.0

        for order in bids:
            px = float(order['px'])
            sz = float(order['sz'])

            if remaining_size <= 0:
                break
            
            size_to_execute = min(remaining_size, sz)
            total_revenue += size_to_execute * px
            total_executed += size_to_execute
            remaining_size -= size_to_execute

        if total_executed == 0:
            return {"error": "No liquidity in the order book"}

        avg_execution_price = total_revenue / total_executed
        
        pnl_before_fee = (avg_execution_price - entry_price) * position_size
        
        # Apply taker fee to the total revenue
        fee = total_revenue * self.maker_fee
        pnl = pnl_before_fee - fee

        timestamp = l2_snapshot['time']
        human_readable_time = datetime.fromtimestamp(timestamp=timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')

        return {
            "position_type": "spot",
            "entry_price": entry_price,
            "execution_price": avg_execution_price,
            "position_size": position_size,
            "fee": fee,
            "pnl": pnl,
            "timestamp": timestamp,
            "human": human_readable_time
        }
    
    def get_latest_consecutive_trades(self, trade_data, trade_type, is_by_time = False):
        """
        Extracts the latest consecutive trades of the specified type, accumulates the total trade size,
        and calculates the average trade price (VWAP - Volume Weighted Average Price).

        :param trade_data: list of dicts, trade history containing 'dir', 'px', and 'sz'.
        :param trade_type: str, the type of trade to search for (e.g., 'Buy', 'Sell', 'Open Short', etc.).
        :param is_by_time: whether trade_data is returned by info.user_fills_by_time(...)
        :return: dict containing total trade size, average trade price, and the latest trades.
        """
        # Extract all unique trade types present in the data
        allowed_trade_types = set(trade["dir"] for trade in trade_data)

        # Validate input trade_type
        if trade_type not in allowed_trade_types:
            return {
                "error": f"Invalid trade type '{trade_type}'. Allowed values: {sorted(allowed_trade_types)}"
            }

        total_size = 0.0  # Sum of trade sizes
        total_cost = 0.0  # Sum of (size * price) for VWAP calculation
        latest_trades = []  # Stores only the latest consecutive trades of the specified type
        trade_started = False  # Flag to track when consecutive trades start

        # If the fills data is returned by calling info.user_fills_by_time()
        if is_by_time:
            trade_data = reversed(trade_data)

        # Iterate to find the latest consecutive trades of the specified type
        for trade in trade_data:
            if trade.get("dir") == trade_type:
                trade_started = True  # Mark that we have started accumulating trades
                px = float(trade["px"])  # Trade price
                sz = float(trade["sz"])  # Trade size
                total_cost += px * sz
                total_size += sz
                latest_trades.append(trade)
            elif trade_started:
                # Stop if we encounter a non-matching trade after starting to accumulate
                break  

        if total_size == 0:
            return {"error": f"No consecutive '{trade_type}' trades found."}

        avg_trade_price = total_cost / total_size  # VWAP Calculation

        return {
            "trade_type": trade_type,
            "total_trade_size": total_size,
            "average_trade_price": avg_trade_price,
            "latest_trades": latest_trades  # Optional: Store the raw trade records
        }

    def run(self, hype_spot="HYPE/USDC", hype_perp="HYPE"):
        l2_snapshot = self.info.l2_snapshot(hype_perp)
        user_state = self.info.user_state(address=self.address)
        entry_price, size = self.extract_entry_price_and_size(user_state=user_state, coin_name=hype_perp) 
        if entry_price is not None and size is not None:
            result = self.calculate_perp_pnl(l2_snapshot, size, entry_price)
            print(json.dumps(result, indent=4))
        else:
            print(f"No {hype_perp} Position Found")

        spot_l2_snapshot = self.info.l2_snapshot(hype_spot)
        accum_result = self.get_latest_consecutive_trades(self.info.user_fills(address=self.address), "Buy")
        spot_size = accum_result['total_trade_size']
        spot_entry_price = accum_result['average_trade_price']
        spot_result = self.calculate_spot_pnl(spot_l2_snapshot, spot_size, spot_entry_price)
        print(json.dumps(spot_result, indent=4))


if __name__ == "__main__":
    calculator = PnLCalculator()
    calculator.run()