# Intro
The gist of this arbitrage is to buy spot and open short such that we get zero risk but at the same time make money through collecting funding payment.

<img width="1434" alt="image" src="https://github.com/user-attachments/assets/293ad4d1-b24d-4757-bce3-f423b27a7549" />

The biggest cost of this arbitrage is trading fee so we spent a lot of time trying to leverage maker fee.

# SpotPerpArb

This is a very rudimentary version of SpotPerpArb on Hyperliquid.

To run the program, first install [hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/)

Second, rename "config.json.example" into "config.json".

Third, set up an Arbitrum account and put its private key in "secret_key" and account address in "account_address" in the "config.json" file you just renamed above.

Run and go.

# Example Log

Check "example_log.txt" to see the log content after program starts running.
