import json
import os

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info


def setup(base_url=None, skip_ws=False):
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)
    account: LocalAccount = eth_account.Account.from_key(config["secret_key"])
    address = config["account_address"]
    if address == "":
        address = account.address
    print("Running with account address:", address)
    if address != account.address:
        print("Running with agent address:", account.address)
    info = Info(base_url, skip_ws)
    user_state = info.user_state(address)
    spot_user_state = info.spot_user_state(address)
    margin_summary = user_state["marginSummary"]
    if float(margin_summary["accountValue"]) == 0 and len(spot_user_state["balances"]) == 0:
        print("Not running the example because the provided account has no equity.")
        url = info.base_url.split(".", 1)[1]
        error_string = f"No accountValue:\nIf you think this is a mistake, make sure that {address} has a balance on {url}.\nIf address shown is your API wallet address, update the config to specify the address of your account, not the address of the API wallet."
        raise Exception(error_string)
    exchange = Exchange(account, base_url, account_address=address)
    return address, info, exchange

def setup_fees():
    """
    Loads taker_fee and maker_fee from the config.json file.
    If the fee field is not present, returns default values.
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)
    
    # Default fees
    default_taker_fee = 0.00035
    default_maker_fee = 0.0001

    # Get fees from config, or use defaults if not present
    fee_config = config.get("fee", {})
    taker_fee = fee_config.get("taker_fee", default_taker_fee)
    maker_fee = fee_config.get("maker_fee", default_maker_fee)

    return taker_fee, maker_fee

def setup_telegram():
    """
    Loads Telegram bot token and chat ID from config.json.
    Returns:
        tuple: (bot_token, chat_id) - both strings
    Raises:
        Exception: If required Telegram config is missing
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)
    
    telegram_config = config.get("telegram", {})
    bot_token = telegram_config.get("bot_token")
    chat_id = telegram_config.get("chat_id")
    
    if not bot_token or not chat_id:
        raise Exception("Telegram bot_token and chat_id must be configured in config.json")
    
    return bot_token, chat_id


def setup_multi_sig_wallets():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path) as f:
        config = json.load(f)

    authorized_user_wallets = []
    for wallet_config in config["multi_sig"]["authorized_users"]:
        account: LocalAccount = eth_account.Account.from_key(wallet_config["secret_key"])
        address = wallet_config["account_address"]
        if account.address != address:
            raise Exception(f"provided authorized user address {address} does not match private key")
        print("loaded authorized user for multi-sig", address)
        authorized_user_wallets.append(account)
    return authorized_user_wallets


def print_json(data:str, indent=4):
    json_data = json.dumps(data, indent=indent)
    print(json_data)


def create_file(data:str, filename: str = None, indent=4):
    with open(f'{filename}.json', 'w') as f:
        json.dump(data, f, indent=indent)
        