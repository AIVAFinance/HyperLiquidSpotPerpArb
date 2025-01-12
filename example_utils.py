import json
import os

import eth_account
from eth_account.signers.local import LocalAccount

from hyperliquid.exchange import Exchange
from hyperliquid.info import Info


def setup(base_url=None, skip_ws=False):
    """
    Initializes the trading environment by loading configuration, verifying account status, 
    and preparing essential components for interaction with Hyperliquid.

    Parameters:
    base_url (str, optional): Base URL of the exchange API. Defaults to None.
    skip_ws (bool, optional): Flag to skip WebSocket connection setup. Defaults to False.

    Returns:
    tuple: A tuple containing the account address (str), an instance of Info (Info), 
           and an instance of Exchange (Exchange).
    
    Raises:
    Exception: If the account has no balance or equity, an error message is raised indicating the issue.
    """
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


def setup_multi_sig_wallets():
    """
    Loads and validates multi-signature wallet configurations, ensuring authorized users' private keys and addresses match.

    Returns:
    list: A list of authorized user wallet accounts (LocalAccount).

    Raises:
    Exception: If an authorized user address does not match the provided private key.
    """
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
    """
    Converts a Python object to a JSON-formatted string and prints it.

    Parameters:
    data (str): The data to be formatted as JSON.
    indent (int, optional): Number of spaces to use for indentation. Defaults to 4.

    Returns:
    None
    """
    json_data = json.dumps(data, indent=indent)
    print(json_data)


def create_file(data:str, indent=4):
    """
    Saves data to a file in JSON format.

    Parameters:
    data (str): The data to be saved to the file.
    indent (int, optional): Number of spaces to use for indentation. Defaults to 4.

    Returns:
    None
    """
    with open('data.json', 'w') as f:
        json.dump(data, f, indent=indent)