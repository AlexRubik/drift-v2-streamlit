## Include a page that analyzes taker execution over a user specified time period (single day, two date range, etc) broken down by market.

### Ideally should include:
### - compare place order auction start/end vs the fill record price
Wrote get_user_orders in user_records.py for this
### - determine the place in the dutch auction (0 -> auction_duration) that the order filled
(lastUpdatedTs - ts) for an order record where "lastActionStatus": "filled". There is no "filled ts" so I assume this is right for now.
### - the fill price vs oracle
Refer to how this is done in tradeflow.py, see comments below.
Also, will need to join trade and order data if we want to simplify the page to use one df because order data is missing oracle price. Otherwise we can just copy tradeflow.py's implementation of price vs oracle.
### - aggregate statistics (mean, median, quantiles) by market on both a price and bps comparison

   -------------------   
### Comments
Assuming we want ALL auction data and not a specified user's data only.

For auction data, you can grab all trades with get_trades_for_range_pandas in api_fetch.py. We do this because we want to grab active accounts in our date range and there is no "get active users in range" endpoint. Use the taker pubkey (user's drift pda aka accountId) from the trade data to fetch the account's orders with get_user_orders I wrote in user_records.py. get_user_orders will give us all of a user's orders (there is no way to filter on date range) that have auction data.

**Problem: If you want to analyze ALL auction data, you will have to do get_user_orders for every account which will take forever because of the 20 record limit on pagination.**


Use this logic for oracle vs fill price
In tradeflow.py:
```
    df1["quoteAssetAmountFilled"] = pd.to_numeric(df1["quoteAssetAmountFilled"])
    df1["baseAssetAmountFilled"] = pd.to_numeric(df1["baseAssetAmountFilled"])
    df1["oraclePrice"] = pd.to_numeric(df1["oraclePrice"])
    df1["markPrice"] = df1["quoteAssetAmountFilled"] / df1["baseAssetAmountFilled"]
    df1["buyPrice"] = np.nan
    df1["sellPrice"] = np.nan
    df1["buyPrice"] = df1.loc[
        df1[df1["takerOrderDirection"] == "long"].index, "markPrice"
    ]
    df1["sellPrice"] = df1.loc[df1["takerOrderDirection"] == "short", "markPrice"]

```