# Intro
The gist of this strategy is to buy spot and open short position in perps such that we get zero risk but still make money by collecting funding payment.

It achieves delta neutrality through the “spot holding + perpetual short” strategy. This approach not only hedges against market price volatility but also allows Aiva Finance to earn stable, risk-free returns from positive funding rates. This strategy is widely used in the digital asset space and is also one of the core methods market makers employ in traditional finance to mitigate price fluctuation risks.

For more info, please visit [Aiva Finance](https://aivafinance.gitbook.io/aivafinance-docs/)

# ⚠️ Disclaimer
**Please note that we are NOT responsible for any loss of funds, damages, or other libailities resulting from the use of this software or any associated services. This tool is provided for educational purposes only and should not be used as financial advice. It is still in expiremental phase so use it at your own risk.**

# SpotPerpArb

To run the strategy,

1st, install [hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk/)

2nd, rename "config.json.example" as "config.json".

3rd, set up an Arbitrum account and put its private key in "secret_key" and account address in "account_address" in the "config.json" file you just renamed above.

Run and go.



# Example Log

Check "example_log.txt" to see the log content after program starts running.


# Further Considerations

1. Basis, i.e. price difference between SPOT and PERP
2. Hedge Ratio
