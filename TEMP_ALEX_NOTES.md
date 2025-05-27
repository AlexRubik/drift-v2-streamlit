## Include a page that analyzes taker execution over a user specified time period (single day, two date range, etc) broken down by market.

### Ideally should include:
### - compare place order auction start/end vs the fill record price
init done
### - determine the place in the dutch auction (0 -> auction_duration) that the order filled
init done
### - the fill price vs oracle
init done
### - aggregate statistics (mean, median, quantiles) by market on both a price and bps comparison
init done

   -------------------   
### Comments

TODO:
- account for oracle records that use price offset?

Suggestions:
- New endpoint to fetch orders in time range
- New endpoint to fetch order actions in time range
- New endpoint to fetch joined order and order action data in time range
- Add oraclePrice field to output of data mentioned above

-----------------
If we want ALL auction data and not a specified user's data only:

For auction data, you can grab all trades with get_trades_for_range_pandas in api_fetch.py. We do this because we want to grab active accounts in our date range and there is no "get active users in range" endpoint. Use the taker pubkey (user's drift pda aka accountId) from the trade data to fetch the account's orders with get_user_orders I wrote in user_records.py. get_user_orders will give us all of a user's orders (there is no way to filter on date range) that have auction data.

**Problem: If you want to analyze ALL auction data, you will have to do get_user_orders for every account which will take forever because of the 20 record limit on pagination.**

This is less of a problem if we want to fetch data for a single user or small array of users which is what we are focusing on.


Test urls:
https://data.api.drift.trade/market/SOL-PERP/trades/2025/05/16
https://data.api.drift.trade/user/GGbgZLcBWDKP1Trhh5vzs9hX3TxDFZPt3oaJRnKwVeB6/trades/2025/05
https://data.api.drift.trade/user/GGbgZLcBWDKP1Trhh5vzs9hX3TxDFZPt3oaJRnKwVeB6/orders/perp/SOL-PERP

References:
https://docs.drift.trade/about-v2/jit-maker-faq

To avoid having an auction, users can set the post-only flag.


Order Record:

```
    {
      "ts": 1747370587,
      "txSig": "5dPZtKjNyEX6DxyHd6gfrN2DnCnrP9nHQyesJ39WBn3ngXXzL6T4U6dKhrBq6VgCsPw3otFGAnvZMyzssnUBXbNF",
      "txSigIndex": 0,
      "slot": 340325521,
      "user": "CemQRxNFqjfYzrzf4ese2VcSqHjcgTXSdutHepMJGec3",
      "status": "open",
      "orderType": "market",
      "marketType": "perp",
      "orderId": 269,
      "userOrderId": 0,
      "marketIndex": 0,
      "price": "0.000000",
      "baseAssetAmount": "88.950000000",
      "quoteAssetAmount": "0.000000",
      "baseAssetAmountFilled": "88.950000000",
      "quoteAssetAmountFilled": "15250.465491",
      "direction": "short",
      "reduceOnly": false,
      "triggerPrice": "0.000000",
      "triggerCondition": "above",
      "existingPositionDirection": "long",
      "postOnly": false,
      "immediateOrCancel": false,
      "oraclePriceOffset": "0.000000",
      "auctionDuration": 0,
      "auctionStartPrice": "0.000000",
      "auctionEndPrice": "0.000000",
      "maxTs": 0,
      "marketFilter": "perp",
      "symbol": "SOL-PERP",
      "lastActionStatus": "filled",
      "lastActionExplanation": "liquidation",
      "lastUpdatedTs": 1747370587
    }
```
