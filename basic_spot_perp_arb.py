from hyperliquid.utils import constants
import logging
import time
import threading
from datetime import datetime

from example_utils import setup, setup_telegram
from PnlCalculator import PnLCalculator
from TelegramNotifier import TelegramNotifier

class HypeSpotPerpArbitrage:
    """
    This strategy intends to buy spot and short perp to earn funding rate from hyperliquid.
    Under current version, we buy spot and sell spot as a maker, leveraging maker fee.
    In the next version, we hope to open short and close short as a maker as well.
    Using maker fee wll earn us more profit more quickly.

    We check funding_rate every 15 minutes and check account_value every 5 minutes.
    """
    def __init__(self, coin):
        self.wallet, self.info, self.exchange = setup(constants.MAINNET_API_URL, skip_ws=True)
        
        self.coin = coin                  # This is for perp trading
        self.pair = self.coin + "/USDC"   # This is for spot trading

        self.logger = None
        self.setup_logger()
        self.logger.info("Initializing Arbitrage Strategy...")
        self.logger.info(f"Trading pair: {self.pair}")

        self.spot_order_result = None
        self.perp_order_result = None
        self.slippage = 0.01    # Used in place_perp_market_order

        self.spot_sz_decimals = self._get_spot_sz_decimals()
        self.perp_sz_decimals = self._get_perp_sz_decimals()

        self.is_perp_open = self._check_perp_open()
        self.is_spot_open = self._check_spot_open()

        self.perp_max_decimals = 6
        self.spot_max_decimals = 8

        self.pnl_calculator = PnLCalculator()

        telegram_bot_token, telegram_chat_id = setup_telegram()
        # Initialize TelegramNotifier if bot_token and chat_id are provided
        if telegram_bot_token and telegram_chat_id:
            self.telegram_notifier = TelegramNotifier(telegram_bot_token, telegram_chat_id)
        else:
            self.telegram_notifier = None

        # The following two attributes are deprecated as is the function check_position_value
        self.initial_position_value = None
        self.position_value_safe_percentage = 0.4
    
    def setup_logger(self):
        """Setup logger to log messages to both console and a log file with a timestamp."""
        log_filename = f"arbitrage_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_filename, mode='a'),  # Append logs to file
                logging.StreamHandler()  # Print logs to console
            ]
        )
        
        self.logger = logging.getLogger(__name__)

    def calculate_and_log_total_pnl(self):
        # Calculate Pnl if positions are closed at the current market price
        perp_pnl = self.calculate_and_log_perp_pnl()
        spot_pnl = self.calculate_and_log_spot_pnl()
        pnl = perp_pnl + spot_pnl
        self.logger.info(f"Total PnL at market price: {pnl}\n")

        # Send Telegram notification if PnL exceeds the threshold
        if self.telegram_notifier:
            message = f"🚨 PnL Alert! Total PnL: ${pnl:.2f}"
            self.telegram_notifier.send_message(message)
    
    def calculate_and_log_perp_pnl(self):
        """Calculate and log PnL for the perpetual position."""
        l2_snapshot = self.info.l2_snapshot(self.coin)
        user_state = self.info.user_state(address=self.wallet)
        entry_price, size = self.pnl_calculator.extract_entry_price_and_size(user_state, self.coin)
        
        if entry_price is not None and size is not None:
            pnl_perp_result = self.pnl_calculator.calculate_perp_pnl(l2_snapshot, size, entry_price)
            self.logger.info(f"[{pnl_perp_result['human']}] Perpetual PnL: {pnl_perp_result['pnl']}")
        else:
            self.logger.info(f"No {self.coin} perpetual position found.")

        return float(pnl_perp_result['pnl'])

    def calculate_and_log_spot_pnl(self):
        """Calculate and log PnL for the spot position."""
        spot_l2_snapshot = self.info.l2_snapshot(self.pair)
        accum_result = self.pnl_calculator.get_latest_consecutive_trades(self.info.user_fills(address=self.wallet), "Buy")
        spot_size = accum_result['total_trade_size']
        spot_entry_price = accum_result['average_trade_price']
        
        pnl_spot_result = self.pnl_calculator.calculate_spot_pnl(spot_l2_snapshot, spot_size, spot_entry_price)
        self.logger.info(f"[{pnl_spot_result['human']}] Spot PnL: {pnl_spot_result['pnl']}")

        return float(pnl_spot_result['pnl'])

    def _check_perp_open(self):
        """
        Check if there are any open positions in the provided data.

        Parameters:
        - data (dict): The dictionary containing margin and position data.

        Returns:
        - bool: True if there are open positions, False otherwise.
        """
        data = self.info.user_state(address=self.wallet)
        # Check if the 'assetPositions' key exists and if it contains any positions
        if 'assetPositions' in data and len(data['assetPositions']) > 0:
            # Iterate through the positions to check if they are open
            for position in data['assetPositions']:
                if position.get('position')['coin'] == self.coin: 
                    self.logger.info(f"Perp position open for {self.coin}.")
                    return True  # There is at least one open position on 'coin'
        return False  # No open positions found
    
    def _check_spot_open(self):
        '''
        We assume spot is open if perp is open.
        '''
        if self.is_perp_open:
            self.logger.info(f"Spot position open for {self.coin}.")
        else:
            return False

    # Function to get USDC(spot) and USDC(perp) balances
    def get_usdc_balances(self):
        """
        Get the USDC(spot) and USDC(perp) balances
        Return {
            'USDC_SPOT': 50.0,
            'USDC_PERP': 50.0
        }
        """
        spot_balance = self.get_spot_balance_by_token("USDC")
        perp_balance = self.get_withdrawable()
        total_balance = spot_balance + perp_balance
        
        return {
            'USDC_SPOT': spot_balance,
            'USDC_PERP': perp_balance,
            'TOTAL': total_balance
        }
    
    # Function to get balance by token_name
    def get_spot_balance_by_token(self, token_name):
        """
        Get the balance of token_name.
        Returns a float representing the balance. If the token is not found, returns 0.0.
        """
        data = self.info.spot_user_state(address=self.wallet)

        for balance in data.get('balances', []):  # Use `.get()` to avoid KeyError
            if balance.get('coin') == token_name:
                try:
                    return float(balance.get('total', 0.0))  # Default to 0.0 if 'total' is missing
                except ValueError:
                    self.logger.warning(f"Invalid balance format for {token_name}, returning 0.0.")
                    return 0.0  # Return 0.0 on parsing failure
        
        self.logger.info(f"Balance for {token_name} not found, returning 0.0.")  # Log missing balance
        return 0.0  # Return 0.0 if the token is not found
    
    # Function to get withdrawable amount in USDC(perp)
    def get_withdrawable(self):
        """
        Get withdrawable in unit of USDC perp
        Return Type is float.
        """
        data = self.info.user_state(address=self.wallet)

        try:
            return float(data.get('withdrawable'))
        except (ValueError, TypeError):
            raise Exception("Invalid withdrawable amount format.")
        
    # Function to get funding rate by token_name
    def get_funding_rate_by_token(self, token_name):
        """
        # Sample context meta data
        data = [
            {
                "universe": [
                    {"szDecimals": 5, "name": "BTC", "maxLeverage": 50},
                    {"szDecimals": 4, "name": "ETH", "maxLeverage": 50}
                ]
            },
            [
                {
                    "funding": "0.0000125",
                    "openInterest": "8267.8146",
                    "prevDayPx": "93789.0",
                    "dayNtlVlm": "1795447570.10542965",
                    "premium": "0.00034473",
                    "oraclePx": "92536.0",
                    "markPx": "92568.0",
                    "midPx": "92570.5",
                    "impactPxs": [
                        "92567.9",
                        "92571.0"
                    ],
                    "dayBaseVlm": "19285.03292"
                },
                {
                    "funding": "0.0000125",
                    "openInterest": "187647.1638",
                    "prevDayPx": "3406.3",
                    "dayNtlVlm": "1400470812.74288845",
                    "premium": "0.00002991",
                    "oraclePx": "3342.9",
                    "markPx": "3343.0",
                    "midPx": "3343.05",
                    "impactPxs": [
                        "3343.0",
                        "3343.1"
                    ],
                    "dayBaseVlm": "415584.6913"
                },
            ]
        ]
        """
        # Get asset context meta data
        data = self.info.meta_and_asset_ctxs()

        # Create a mapping of token names to funding rates
        universe = data[0]['universe']
        token_map = {token['name']: index for index, token in enumerate(universe)}

        # Extract funding rates (second list in the data)
        funding_data = data[1]
        
        # Check if token exists in the mapping
        if token_name in token_map:
            index = token_map[token_name]
            if index < len(funding_data):
                return float(funding_data[index]['funding'])
            else:
                return f"Funding data for {token_name} not found."
        else:
            return f"Token {token_name} not found in universe."

    # Function to get mark price by token_name
    def get_markPx_by_token(self, token_name):
        token_mark_price = self._get_token_markPx()
        if token_name in token_mark_price:
            return token_mark_price[token_name]
        else:
            self.logger.info(f"There is no mark price for {token_name}. We'll just return 0.0.")
            return 0.0

    def _get_token_markPx(self):
        """
        Returns a dict,{token_name: mark_prie}
        """
        # Get meta and asset context info
        data = self.info.meta_and_asset_ctxs() 

        # Extract token names from the universe list
        token_names = [item['name'] for item in data[0]['universe']]
        
        # Extract markPx values from the market data and map them to token names
        token_mark_pxs = {}
        for i, item in enumerate(data[1]):
            if i < len(token_names):
                token_mark_pxs[token_names[i]] = float(item.get('markPx'))
        
        return token_mark_pxs

    def _get_perp_sz_decimals(self):
        # Get the exchange's metadata and print it out
        meta = self.info.meta()
        # print(json.dumps(meta, indent=2))

        # create a szDecimals map
        perp_sz_decimals = {}
        for asset_info in meta["universe"]:
            perp_sz_decimals[asset_info["name"]] = asset_info["szDecimals"]

        return perp_sz_decimals
    
    def _get_spot_sz_decimals(self):
        # Get the exchange's metadata and print it out
        meta = self.info.spot_meta()
        # print(json.dumps(meta, indent=2))

        spot_sz_decimals = {}
        for asset_info in meta["tokens"]:
            spot_sz_decimals[asset_info["name"]] = asset_info["szDecimals"]
        
        return spot_sz_decimals

    def _round_perp_px_sz(self, px, sz):
        # If you use these directly, the exchange will return an error, so we round them.
        # First we check if price is greater than 100k in which case we just need to round to an integer
        if px > 100_000:
            px = round(px)
        # If not we round px to 5 significant figures and max_decimals - szDecimals decimals
        else:
            px = round(float(f"{px:.5g}"), self.perp_max_decimals - self.perp_sz_decimals[self.coin])

        # Truncate sz to the specified number of decimal places
        # Here we truncate sz because rounding sometimes rounds up a number, making sz*pz greater than original sz*pz.
        decimal_places = self.perp_sz_decimals[self.coin]
        factor = 10 ** decimal_places
        sz = int(sz * factor) / factor

        return px, sz

    def _round_spot_px_sz(self, px, sz):
        # If you use these directly, the exchange will return an error, so we round them.
        # First we check if price is greater than 100k in which case we just need to round to an integer
        if px > 100_000:
            px = round(px)
        # If not we round px to 5 significant figures and max_decimals - szDecimals decimals
        else:
            px = round(float(f"{px:.5g}"), self.spot_max_decimals - self.spot_sz_decimals[self.coin])

        # # Next we round sz based on the sz_decimals map we created
        # sz = round(sz, self.spot_sz_decimals[self.coin])
        
        # Truncate sz to the specified number of decimal places
        # # Here we truncate sz because rounding sometimes rounds up a number, making sz*pz greater than original sz*pz.
        decimal_places = self.spot_sz_decimals[self.coin]
        factor = 10 ** decimal_places
        sz = int(sz * factor) / factor

        return px, sz

    def place_spot_limit_order(self, is_buy=True):
            # Place limit order buy at the first ask price
        if is_buy:
            price = self._spot_bid_price_at_level(1)
            size = self.allocation / price
        else:
            # Place limit order sell at the first bid price
            # And sell all the spot balance
            price = self._spot_ask_price_at_level(1)
            size = self.get_spot_balance_by_token(self.coin)

        # Round the price and size to be compliant with hyperliquid's requirement
        price, size = self._round_spot_px_sz(price, size)

        # Using self.pair means this is a SPOT order.
        self.spot_order_result = self.exchange.order(self.pair, is_buy, size, price, {"limit": {"tif": "Gtc"}})

        # Query the order status by oid and Wait for spot order to be filled before continue
        # The Waiting part only works when we place limit order.
        if self.spot_order_result["status"] == "ok":
            status = self.spot_order_result["response"]["data"]["statuses"][0]
            if "resting" in status:
                oid = status["resting"]["oid"]
                order_status = self.exchange.info.query_order_by_oid(self.wallet, oid)
                self.logger.info("Order status by oid:", order_status)

                # Wait until filled
                while True:
                    order_status = self.exchange.info.query_order_by_oid(self.wallet, oid)
                    if order_status['order']['status'] == 'filled':
                        break

                    if is_buy:
                        self.logger.info("Waiting for spot buy order to be filled.")
                    else:
                        self.logger.info("Waiting for spot sell order to be filled.")

        return self.spot_order_result
    
    def _spot_ask_price_at_level(self, level):
        data = self.info.l2_snapshot(self.pair)
        asks = data['levels'][1]  # Second list in 'levels' is asks
        return float(asks[level]['px'])
    
    def _perp_ask_price_at_level(self, level):
        data = self.info.l2_snapshot(self.coin)
        asks = data['levels'][1]  # Second list in 'levels' is asks
        return float(asks[level]['px'])

    def _spot_bid_price_at_level(self, level):
        data = self.info.l2_snapshot(self.pair)
        bids = data['levels'][0]  # First list in 'levels' is bids
        return float(bids[level]['px'])

    def _perp_bid_price_at_level(self, level):
        data = self.info.l2_snapshot(self.coin)
        bids = data['levels'][0]  # First list in 'levels' is bids
        return float(bids[level]['px'])
        
    # Currently, we are NOT using this function to place perp order.  
    def place_perp_limit_order(self, size, price, is_buy=False):
        self.perp_order_result = self.exchange.order(self.coin, is_buy, size, price, {"limit": {"tif": "Gtc"}})
        return self.perp_order_result   

    def place_perp_market_order(self, is_buy=False):
        # Here the size means the units of coin rather than the units of USDC
        size = self.get_spot_balance_by_token(self.coin)
        # price = self._perp_ask_price_at_level(1)

        if not size > 0:
            self.logger.info(f"No spot balance. Spot Buy May NOT SUCCEED.")
            return
        
        _, size = self._round_perp_px_sz(0.0, size)

        self.logger.info(f"There are {size} {self.coin} in the balance.")
        self.logger.info(f"We are going to open corresponding amount of short position.")

        self.perp_order_result = self.exchange.market_open(self.coin, is_buy, size, slippage=self.slippage)
        if self.perp_order_result["status"] == "ok":
            for status in self.perp_order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    self.logger.info(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    self.logger.info(f'Error: {status["error"]}')        

        return self.perp_order_result

    def close_positions(self):   
        # Sell all spot 
        self.logger.info(f"We try to sell all {self.coin}.")
        coin_spot_balance = self.get_spot_balance_by_token(self.coin)
        if coin_spot_balance > 0:
            self.place_spot_limit_order(is_buy=False)
        else:
            self.logger.info(f"No spot balance. Nothing to sell.")
            
        # Close short perp
        self.logger.info(f"Now we try to close all {self.coin}.")
        order_result = self.exchange.market_close(self.coin)
        if order_result["status"] == "ok":
            for status in order_result["response"]["data"]["statuses"]:
                try:
                    filled = status["filled"]
                    self.logger.info(f'Order #{filled["oid"]} filled {filled["totalSz"]} @{filled["avgPx"]}')
                except KeyError:
                    self.logger.info(f'Error: {status["error"]}')

    def allocate_spot_perp_balance(self):
        """
        Evenly allocate spot and perp usdc balance;
        In a word, rebalance the balance.
        Return the evenly allocated balance, which is half the total.
        """
        balances = self.get_usdc_balances()
        usdc_spot = balances['USDC_SPOT']
        usdc_perp = balances['USDC_PERP']
        total_usdc = balances['TOTAL']
        allocation = total_usdc / 2

        self.logger.info(f"The current usdc_spot is {usdc_spot} and usdc_perp is {usdc_perp}.")

        # If usdc_perp > usdc_spot, transfer (usdc_perp - usdc_spot)/2 from perp to spot
        # If usdc_perp < usdc_spot, transfer (usdc_spot - usdc_perp)/2 from spot to perp
        if usdc_perp > usdc_spot:
            transfer_amount = (usdc_perp - usdc_spot) / 2
            transfer_result = self.exchange.usd_class_transfer(transfer_amount, False)
            self.logger.info("Since usdc_perp > usdc_spot, transfer from perp to spot: ", transfer_result)
        else:
            transfer_amount = (usdc_spot - usdc_perp) / 2
            transfer_result = self.exchange.usd_class_transfer(transfer_amount, True)
            self.logger.info("Since usdc_spot > usdc_perp, transfer from spot to perp: ", transfer_result)
        
        new_balances = self.get_usdc_balances()
        new_usdc_spot = new_balances['USDC_SPOT']
        new_usdc_perp = new_balances['USDC_PERP']

        if abs(new_usdc_perp - allocation) < 0.0001 and abs(new_usdc_spot - allocation) < 0.0001:
            self.logger.info(f"The usdc_spot is {new_usdc_spot} and the usdc_perp is {new_usdc_perp}")
            self.logger.info(f"Allocation complete and successful.")
        
        return allocation

    # This function is used in check_positions_value, which is deprecated.
    def get_position_value(self):
        """
        Extracts the position value from the provided data structure.
        
        Position Value = Position Size * Mark Price

        Parameters:
        - data (dict): The input data containing position details.

        # Example usage:
        data = {
            "marginSummary": {
                "accountValue": "49.589238",
                "totalNtlPos": "50.26905",
                "totalRawUsd": "99.858288",
                "totalMarginUsed": "50.26905"
            },
            "crossMarginSummary": {
                "accountValue": "49.589238",
                "totalNtlPos": "50.26905",
                "totalRawUsd": "99.858288",
                "totalMarginUsed": "50.26905"
            },
            "crossMaintenanceMarginUsed": "8.378175",
            "withdrawable": "0.0",
            "assetPositions": [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": "HYPE",
                        "szi": "-1.95",
                        "leverage": {
                            "type": "cross",
                            "value": 1
                        },
                        "entryPx": "25.578",
                        "positionValue": "50.26905",
                        "unrealizedPnl": "-0.39195",
                        "returnOnEquity": "-0.00785832",
                        "liquidationPx": "43.89375297",
                        "marginUsed": "50.26905",
                        "maxLeverage": 3,
                        "cumFunding": {
                            "allTime": "-0.089456",
                            "sinceOpen": "-0.002625",
                            "sinceChange": "-0.002625"
                        }
                    }
                }
            ],
            "time": 1736219976887
        }

        Returns:
        - float: The value of position_value if found, otherwise None.
        """
        try:
            data = self.info.user_state(address=self.wallet)
            # Navigate through the structure to find the position_value
            position_value = data['assetPositions'][0]['position']['positionValue']
            return float(position_value)  # Convert the position value to float
        except (KeyError, IndexError) as e:
            self.logger.info(f"Error extracting position_value: {e}")
            self.logger.info(f"Possibly because the system just closed positions. Please wait for 30 minutes.")
            return None
    
    # This function is deprecated.
    def check_position_value(self):
        """
        Checks if position value has fallen by 60% every 5 minutes.
        This function is deprecated since position value is not account value.
        """
        while True:
            try:
                if self.initial_position_value:
                    current_position_value = self.get_position_value()

                    # Calculate the 40% fall threshold
                    threshold = self.initial_position_value * self.position_value_safe_percentage

                    # If the position value has fallen below 40% of the original value, close the positions
                    if current_position_value <= threshold:
                        self.logger.info(f"Position value fell by 40% (current: {current_position_value}, threshold: {threshold}). Closing positions.")
                        self.close_positions()
                        self.is_spot_open = False
                        self.is_perp_open = False
                    else:
                        self.logger.info(f"Position value is safe. Current: {current_position_value}, Threshold: {threshold}")

                # Sleep for 5 minutes before checking the position value again
                time.sleep(5 * 60)

            except Exception as e:
                self.logger.info(f"Position value check error: {e}")
                time.sleep(60)
    
    def check_funding_rate(self):
        """Checks the funding rate every 15 mins and manages positions."""
        while True:
            try:
                funding_rate = self.get_funding_rate_by_token(self.coin)
                
                # Send a Telegram notification about the funding rate
                if self.telegram_notifier:
                    message = f"📊 Current funding rate for {self.coin}: {funding_rate}"
                    self.telegram_notifier.send_message(message)

                # Only operate when the funding rate is positive
                if funding_rate > 0:
                    self.logger.info(f"Funding rate {funding_rate} is positive.")
                    if not self.is_spot_open and not self.is_perp_open:
                        self.allocation = self.allocate_spot_perp_balance()
                        self.place_spot_limit_order(is_buy=True)
                        self.is_spot_open = True
                        self.place_perp_market_order(is_buy=False)
                        self.is_perp_open = True
                    else:
                        self.logger.info(f"Orders are already open.")
                
                else:
                    self.logger.info(f"Funding rate is {funding_rate}, negative.")
                    if self.is_spot_open and self.is_perp_open:
                        self.logger.info(f"We close positions.")
                        self.close_positions()
                        self.is_spot_open = False
                        self.is_perp_open = False
                        self.logger.info(f"Positions closed.")

                # Sleep for 15 minutes before checking the funding rate again
                time.sleep(15 * 60)

            except Exception as e:
                self.logger.error(f"⚠️ Funding rate check error: {e}")
                if self.telegram_notifier:
                    error_message = f"⚠️ Error in funding rate check: {e}"
                    self.telegram_notifier.send_message(error_message)
                time.sleep(60)

    def check_account_value(self):
        while True:
            try:
                self.logger.info("🔍 Running Account Value Check...")  # Heartbeat log

                user_state = self.info.user_state(address=self.wallet)
                if self.is_perp_open:
                    relevant_values = self._extract_relevant_values(user_state)
                    self._check_and_warn(relevant_values)
                else:
                    self.logger.info("ℹ️ Perpetual positions are not open yet. Skipping check.")

                # Sleep for 5 minutes before checking the account value again
                time.sleep(5 * 60)

            except Exception as e:
                self.logger.error(f"⚠️ Account value check error: {e}")
                time.sleep(60)

    def _extract_relevant_values(self, user_state):
        """
        Extracts relevant values from the provided data，i.e. info.user_state
        
        Parameters:
            data (dict): JSON data containing margin and position details.
        
        Returns:
            dict: A dictionary containing the relevant extracted values.

            # Example data from your JSON
        data = {
            "marginSummary": {
                "accountValue": "58.747197",
                "totalNtlPos": "41.356",
                "totalRawUsd": "100.103197",
                "totalMarginUsed": "41.356"
            },
            "crossMarginSummary": {
                "accountValue": "58.747197",
                "totalNtlPos": "41.356",
                "totalRawUsd": "100.103197",
                "totalMarginUsed": "41.356"
            },
            "crossMaintenanceMarginUsed": "6.892666",
            "assetPositions": [
                {
                    "type": "oneWay",
                    "position": {
                        "coin": "HYPE",
                        "szi": "-1.96",
                        "leverage": {
                            "type": "cross",
                            "value": 1
                        },
                        "entryPx": "25.454",
                        "positionValue": "41.356",
                        "unrealizedPnl": "8.53384",
                        "returnOnEquity": "0.17105367",
                        "liquidationPx": "43.7769086",
                        "marginUsed": "41.356",
                        "maxLeverage": 3,
                        "cumFunding": {
                            "allTime": "-0.330918",
                            "sinceOpen": "-0.236496",
                            "sinceChange": "-0.236496"
                        }
                    }
                }
            ],
            "time": 1736481449739
        }
        """
        data = user_state

        # Extract relevant values
        account_value = float(data["crossMarginSummary"]["accountValue"])
        cross_maintenance_margin_used = float(data["crossMaintenanceMarginUsed"])
        position = data["assetPositions"][0]["position"]
        liquidation_price = float(position["liquidationPx"])
        mark_price = self.get_markPx_by_token(self.coin) 
        
        # Return extracted values as a dictionary
        return {
            "account_value": account_value,
            "maintenance_margin": cross_maintenance_margin_used,
            "liquidation_price": liquidation_price,
            "mark_price": mark_price
        }

    def _check_and_warn(self, relevant_values):
        """
        Checks if the account value is close to the maintenance margin or the price is near liquidation.
        Generates warnings if necessary.
        
        Parameters:
            values (dict): Dictionary of extracted relevant values.
            
            {
                "account_value": account_value,
                "maintenance_margin": cross_maintenance_margin_used,
                "liquidation_price": liquidation_price,
                "current_price": current_price
            }
        
        Returns:
            None
        """
        values = relevant_values

        # Unpack values
        account_value = values["account_value"]
        maintenance_margin = values["maintenance_margin"]
        liquidation_price = values["liquidation_price"]
        mark_price = values["mark_price"]
        
        # Define a warning threshold (e.g., account value close to 1.2x maintenance margin)
        warning_threshold = maintenance_margin * 1.2

        self.logger.info(f"Account Value: {account_value}")
        self.logger.info(f"Cross Maintenance Margin Used: {maintenance_margin}")
        self.logger.info(f"Warning Threshold: {warning_threshold}")
        self.logger.info(f"Liquidation Price: {liquidation_price}")
        self.logger.info(f"Mark Price: {mark_price}")
        
        # Check if account value is close to or below the threshold
        if account_value <= warning_threshold:
            self.logger.info(f"⚠️ Warning: Account value is close to the maintenance margin threshold.")
            self.logger.info("Consider reducing your position to avoid liquidation!")
        elif mark_price >= liquidation_price:
            self.logger.info(f"⚠️ Warning: The current mark price is close to the liquidation price!")
            self.logger.info("Consider taking action to avoid liquidation!")
        else:
            self.logger.info(f"✅ Your account is safe for now.\n")

        # Calculate the pnl if we close short and sell spot at the current market price immediately.
        self.calculate_and_log_total_pnl()

    # This is currently deprecated with the introduction of Logging
    def _curr_timestamp(self):
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def run_strategy(self):
        # Run the strategy functions in separate threads to allow parallel execution
        funding_rate_thread = threading.Thread(target=self.check_funding_rate)
        account_value_thread = threading.Thread(target=self.check_account_value)

        # Start the threads
        self.logger.info("Starting Funding Rate Monitoring Thread...")
        self.logger.info("Starting Account Value Monitoring Thread...")
        
        funding_rate_thread.start()
        account_value_thread.start()

        self.logger.info("Both strategy threads have been started successfully.")

        # Join the threads to run the strategy until completion
        funding_rate_thread.join()
        account_value_thread.join()           

if __name__ == "__main__":
    arbitrage = HypeSpotPerpArbitrage("HYPE")
    # arbitrage.close_positions()
    arbitrage.run_strategy()