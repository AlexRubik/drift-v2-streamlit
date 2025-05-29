import time
from datetime import date, datetime
from typing import Union, List

import pandas as pd
import requests
from solders.pubkey import Pubkey
from streamlit import cache_data

URL_PREFIX = "https://data.api.drift.trade"


@cache_data(ttl=5)
def _fetch_user_records(
    record_type: str, user_public_key: str, start_date: date, end_date: date
):
    """Fetches paginated records for a user from the API between two dates, iterating through months."""
    print(
        f"Fetching {record_type} for {user_public_key} from {start_date} to {end_date} by month..."
    )

    all_records = []

    # Generate list of months to iterate through
    months_to_fetch = []
    current_month_start = date(start_date.year, start_date.month, 1)
    while current_month_start <= end_date:
        months_to_fetch.append((current_month_start.year, current_month_start.month))
        # Move to the next month
        next_month_year = current_month_start.year
        next_month = current_month_start.month + 1
        if next_month > 12:
            next_month = 1
            next_month_year += 1
        current_month_start = date(next_month_year, next_month, 1)

    print(f"Target months: {months_to_fetch}")

    for year, month in months_to_fetch:
        page = 1
        url_month_base = (
            f"{URL_PREFIX}/user/{str(user_public_key)}/{record_type}/{year}/{month:02}"
        )
        print(f"-- Fetching {record_type} for {year}-{month:02} from {url_month_base}")

        while True:
            try:
                params = {"page": page}
                response = requests.get(url_month_base, params=params)

                # Handle potential 404 for months with no data
                if response.status_code == 404:
                    print(
                        f"No {record_type} data found for {year}-{month:02} (404). Skipping month."
                    )
                    break

                response.raise_for_status()  # Raise for other errors (5xx, 4xx)
                json_data = response.json()
                meta = json_data.get("meta", {})
                records = json_data.get("records", [])

                if not records:
                    print(
                        f"No more {record_type} records found for {year}-{month:02} on page {page}."
                    )
                    break

                all_records.extend(records)
                print(
                    f"Fetched page {page} for {year}-{month:02} with {len(records)} {record_type} records."
                )

                next_page = meta.get("nextPage")
                if next_page is None:
                    print(
                        f"Reached end of {record_type} records for {year}-{month:02}."
                    )
                    break

                page = next_page
                time.sleep(0.1)  # Be nice to the API

            except requests.exceptions.RequestException as e:
                print(
                    f"Error fetching {record_type} data for {user_public_key} ({year}-{month:02}) on page {page}: {e}"
                )
                # Decide if we should retry or break for this month
                break
            except Exception as e:
                print(
                    f"Unexpected error fetching {record_type} for {year}-{month:02}: {e}"
                )
                break

    df = pd.DataFrame(all_records)
    if df.empty:
        print(
            f"Finished fetching {record_type}. No records found in any fetched month."
        )
        return df

    # Convert timestamp and filter based on exact start/end date
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="s")

        # Convert start_date and end_date to datetime objects for comparison
        start_dt = datetime.combine(start_date, datetime.min.time())
        # End date filtering should be inclusive, so compare up to the end of the end_date day
        end_dt = datetime.combine(end_date, datetime.max.time())

        original_count = len(df)
        df = df[(df["ts"] >= start_dt) & (df["ts"] <= end_dt)]
        filtered_count = len(df)
        print(
            f"Filtered records by date range ({start_dt} to {end_dt}): {original_count} -> {filtered_count}"
        )

        df = df.sort_values("ts").reset_index(drop=True)
    else:
        print(
            f"Warning: 'ts' column not found in {record_type} records. Cannot sort or filter by time."
        )

    print(
        f"Finished fetching {record_type}. Total records after date filtering: {len(df)}"
    )
    return df


def get_user_trades(
    user_public_key: Pubkey, start_date: date, end_date: date
) -> pd.DataFrame:
    return _fetch_user_records("trades", str(user_public_key), start_date, end_date)


def get_user_settle_pnls(
    user_public_key: Pubkey, start_date: date, end_date: date
) -> pd.DataFrame:
    return _fetch_user_records("settlePnls", str(user_public_key), start_date, end_date)


def get_user_deposits(
    user_public_key: Pubkey, start_date: date, end_date: date
) -> pd.DataFrame:
    return _fetch_user_records("deposits", str(user_public_key), start_date, end_date)


def get_user_withdrawals(
    user_public_key: Pubkey, start_date: date, end_date: date
) -> pd.DataFrame:
    return _fetch_user_records(
        "withdrawals", str(user_public_key), start_date, end_date
    )


def get_user_funding(
    user_public_key: Pubkey, start_date: date, end_date: date
) -> pd.DataFrame:
    return _fetch_user_records("funding", str(user_public_key), start_date, end_date)


def get_user_orders(
    user_public_key: str, 
    market_filter: str, 
    symbol: str, 
    pages_max: int = None, 
    post_only: bool = False,
    last_action_status: str = None,
    order_type: Union[str, List[str]] = None,
    exclude_liquidations: bool = False
):
    """
    Fetches order records for a specific user and market.
    
    Args:
        user_public_key: The public key of the user account
        market_filter: The market type ('spot', 'perp', or 'prediction')
        symbol: The market symbol (e.g., 'SOL-PERP', 'SOL')
        pages_max: Maximum number of pages to fetch (None for all pages)
        post_only: If True, returns only orders that requested post-only (postOnly=True)
        last_action_status: Filter for specific lastActionStatus (e.g., 'filled', 'canceled')
        order_type: Filter for specific order type (e.g., 'limit', 'market', 'oracle')
        exclude_liquidations: If True, excludes orders with lastActionExplanation='liquidation'
        
    Returns:
        DataFrame containing order records sorted by lastUpdatedTs
    """
    print(f"Fetching orders for {user_public_key} in {market_filter} market {symbol}...")
    
    all_records = []
    next_page_token = None
    page_count = 1
    
    
    while pages_max is None or page_count <= pages_max:
        try:
            url = f"{URL_PREFIX}/user/{user_public_key}/orders/{market_filter}/{symbol}"
            params = {}
            
            # Add the next page token if we have one
            if next_page_token:
                params["page"] = next_page_token
            
            response = requests.get(url, params=params)
            
            # Handle potential 404 for users with no orders
            if response.status_code == 404:
                print(f"No order data found for {user_public_key} in {market_filter} market {symbol} (404).")
                break
                
            response.raise_for_status()  # Raise for other errors (5xx, 4xx)
            json_data = response.json()
            
            records = json_data.get("records", [])
            meta = json_data.get("meta", {})
            
            if not records:
                print(f"No more order records found for {user_public_key}.")
                break
                
            all_records.extend(records)
            print(f"Fetched page {page_count} with {len(records)} order records.")
            
            # Get the next page token from the meta data
            next_page_token = meta.get("nextPage")
            if next_page_token is None:
                print(f"Reached end of order records for {user_public_key}.")
                break
                
            page_count += 1
            time.sleep(0.1)  # Be nice to the API
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching order data: {e}")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            break
    
    if not all_records:
        print(f"No order records found for {user_public_key} in {market_filter} market {symbol}.")
        return pd.DataFrame()
        
    # Convert to DataFrame
    df = pd.DataFrame(all_records)
    
    # Log order type counts before filtering
    if 'orderType' in df.columns:
        order_type_counts = df['orderType'].value_counts()
        print("\nOrder type distribution before filtering:")
        for ot, count in order_type_counts.items():
            print(f"  {ot}: {count} orders")
    
    # Log lastActionStatus counts before filtering
    if 'lastActionStatus' in df.columns:
        status_counts = df['lastActionStatus'].value_counts()
        print("\nOrder status distribution before filtering:")
        for status, count in status_counts.items():
            print(f"  {status}: {count} orders")
    
    # Log lastActionExplanation counts before filtering
    if 'lastActionExplanation' in df.columns:
        explanation_counts = df['lastActionExplanation'].value_counts()
        print("\nOrder explanation distribution before filtering:")
        for explanation, count in explanation_counts.items():
            print(f"  {explanation}: {count} orders")
    
    # Log postOnly counts before filtering
    if 'postOnly' in df.columns:
        postonly_counts = df['postOnly'].value_counts()
        print("\nPost-only distribution before filtering:")
        for is_postonly, count in postonly_counts.items():
            label = "Post-only" if is_postonly else "Auction"
            print(f"  {label}: {count} orders")
    
    # Apply filters
    original_count = len(df)
    
    # Filter for auction orders only if requested
    # To avoid having an auction, users can set the post-only flag.
    if not post_only and 'postOnly' in df.columns:
        df = df[df['postOnly'] == False]
        print(f"\nFiltered for auction orders only: {original_count} -> {len(df)}")
        original_count = len(df)
    
    # Filter by lastActionStatus if specified
    if last_action_status and 'lastActionStatus' in df.columns:
        df = df[df['lastActionStatus'] == last_action_status]
        print(f"Filtered for lastActionStatus={last_action_status}: {original_count} -> {len(df)}")
        original_count = len(df)
    
    # Filter by order type if specified
    if order_type and 'orderType' in df.columns:
        if isinstance(order_type, list):
            df = df[df['orderType'].isin(order_type)]
            print(f"Filtered for orderTypes={order_type}: {original_count} -> {len(df)}")
        else:
            df = df[df['orderType'] == order_type]
            print(f"Filtered for orderType={order_type}: {original_count} -> {len(df)}")
        original_count = len(df)
    
    # Exclude liquidations if requested
    if exclude_liquidations and 'lastActionExplanation' in df.columns:
        df = df[df['lastActionExplanation'] != 'liquidation']
        print(f"Excluded liquidation orders: {original_count} -> {len(df)}")
    
    # Convert timestamp columns to datetime
    timestamp_columns = ['ts', 'maxTs', 'lastUpdatedTs']
    for col in timestamp_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s')
    
    # Sort by lastUpdatedTs (newest first)
    if 'ts' in df.columns:
        df = df.sort_values('ts', ascending=False).reset_index(drop=True)
    
    print(f"\nFinished fetching orders. Total records after filtering: {len(df)}")
    return df


# @cache_data(ttl=60 * 15)
# def get_user_liquidations(user_public_key: Pubkey, start_date: date, end_date: date) -> pd.DataFrame:
#     # Assuming liquidations are less frequent, might need different handling or endpoint structure
#     return _fetch_user_records("liquidations", user_public_key, start_date, end_date)


def get_user_order_actions(user_public_key: str, order_id: str):
    """
    Fetches all actions for a specific order ID of a user.
    
    Args:
        user_public_key: The public key of the user account
        order_id: The ID of the order to fetch actions for
        
    Returns:
        DataFrame containing all actions for the specified order
    """
    print(f"Fetching order actions for user {user_public_key}, order ID {order_id}...")
    
    all_records = []
    next_page_token = None
    page_count = 1
    
    while True:
        try:
            url = f"{URL_PREFIX}/user/{user_public_key}/orders/{order_id}/actions"
            params = {}
            
            # Add the next page token if we have one
            if next_page_token:
                params["page"] = next_page_token
            
            response = requests.get(url, params=params)
            
            # Handle potential 404 for users with no orders
            if response.status_code == 404:
                print(f"No order actions found for user {user_public_key}, order ID {order_id} (404).")
                break
                
            response.raise_for_status()  # Raise for other errors (5xx, 4xx)
            json_data = response.json()
            
            records = json_data.get("records", [])
            meta = json_data.get("meta", {})
            
            if not records:
                print(f"No more order action records found for order ID {order_id}.")
                break
                
            all_records.extend(records)
            print(f"Fetched page {page_count} with {len(records)} order action records.")
            
            # Get the next page token from the meta data
            next_page_token = meta.get("nextPage")
            if next_page_token is None:
                print(f"Reached end of order action records for order ID {order_id}.")
                break
                
            page_count += 1
            time.sleep(0.1)  # Be nice to the API
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching order action data: {e}")
            break
        except Exception as e:
            print(f"Unexpected error: {e}")
            break
    
    if not all_records:
        print(f"No order action records found for user {user_public_key}, order ID {order_id}.")
        return pd.DataFrame()
        
    # Convert to DataFrame
    df = pd.DataFrame(all_records)
    
    # Convert timestamp columns to datetime
    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'], unit='s')
    
    # Sort by timestamp (newest first)
    if 'ts' in df.columns:
        df = df.sort_values('ts', ascending=False).reset_index(drop=True)
    
    print(f"Finished fetching order actions. Total records: {len(df)}")
    return df


def calculate_auction_slot_diff(actions_df, order_id):
    """
    Calculate the slot difference between placing an order and its final fill.
    
    Args:
        actions_df: DataFrame containing order actions
        order_id: The order ID to calculate slot difference for
        
    Returns:
        The slot difference (final fill slot - place slot) or None if not found
    """
    # Filter actions for this specific order
    order_actions = actions_df[actions_df['orderId'] == order_id]
    
    if order_actions.empty:
        return None
    
    # Get the place order slot
    place_actions = order_actions[order_actions['action'] == 'place']
    if place_actions.empty:
        return None
    
    place_slot = place_actions.iloc[0]['slot']
    
    # Get all fill actions for this order
    fill_actions = order_actions[order_actions['action'] == 'fill']
    if fill_actions.empty:
        return None
    
    # Find the final fill where takerOrderBaseAssetAmount equals takerOrderCumulativeBaseAssetAmountFilled
    final_fills = fill_actions[
        (fill_actions['takerOrderBaseAssetAmount'] == fill_actions['takerOrderCumulativeBaseAssetAmountFilled']) |
        (fill_actions['makerOrderBaseAssetAmount'] == fill_actions['makerOrderCumulativeBaseAssetAmountFilled'])
    ]
    
    if final_fills.empty:
        return None
    
    # Get the slot number for the final fill
    final_fill_slot = final_fills.iloc[0]['slot']
    
    # Calculate the absolute difference
    slot_diff = abs(final_fill_slot - place_slot)
    
    return slot_diff

def get_user_orders_and_actions(
    user_public_key: str, 
    market_filter: str, 
    symbol: str,
    start_date: date,
    end_date: date,
    pages_max: int = None, 
    post_only: bool = False,
    last_action_status: str = None,
    order_type: Union[str, List[str]] = None,
    exclude_liquidations: bool = False,
    auction_orders_only: bool = False
):
    """
    Fetches order records for a specific user and market, along with all actions for those orders.
    
    Args:
        user_public_key: The public key of the user account
        market_filter: The market type ('spot', 'perp', or 'prediction')
        symbol: The market symbol (e.g., 'SOL-PERP', 'SOL')
        pages_max: Maximum number of pages to fetch (None for all pages)
        post_only: If True, returns only orders that requested post-only (postOnly=True)
        last_action_status: Filter for specific lastActionStatus (e.g., 'filled', 'canceled')
        order_type: Filter for specific order type or list of types (e.g., 'limit', 'market', 'oracle')
        exclude_liquidations: If True, excludes orders with lastActionExplanation='liquidation'
        auction_orders_only: If True, returns only orders with auction data (auctionDuration > 0 or auctionStartPrice != 0)
        
    Returns:
        Tuple containing five DataFrames:
        - orders_df: DataFrame with order records
        - actions_df: DataFrame with all actions for all orders
        - joined_df: DataFrame with orders joined with their actions
        - auction_slot_diff_df: DataFrame with orders and their auction slot differences
        - auction_metrics_df: Simplified DataFrame with key auction metrics and fill price
    """
    print(f"Fetching orders and actions for {user_public_key} in {market_filter} market {symbol}...")
    
    # First, get all orders using the existing function
    orders_df = get_user_orders(
        user_public_key=user_public_key,
        market_filter=market_filter,
        symbol=symbol,
        pages_max=pages_max,
        post_only=post_only,
        last_action_status=last_action_status,
        order_type=order_type,
        exclude_liquidations=exclude_liquidations
    )
    
    if orders_df.empty:
        print(f"No orders found for {user_public_key} in {market_filter} market {symbol}.")
        return orders_df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    # filter on start and end date
    if start_date and end_date:
        print(f"Filtering orders on start date {start_date} and end date {end_date}")
        # convert start and end date to datetime unix timestamp
        start_date_unix = int(datetime(start_date.year, start_date.month, start_date.day).timestamp())
        end_date_unix = int(datetime(end_date.year, end_date.month, end_date.day).timestamp())
        
        # Convert DataFrame timestamps to Unix seconds for comparison
        orders_df['ts'] = pd.to_datetime(orders_df['ts']).astype(int) // 10**9
        
        original_length = len(orders_df)
        orders_df = orders_df[
            (orders_df['ts'] >= start_date_unix) & 
            (orders_df['ts'] <= end_date_unix)
        ]
        
        # Convert timestamps back to datetime
        orders_df['ts'] = pd.to_datetime(orders_df['ts'], unit='s')
        
        print(f"Filtered orders by date range: {original_length} -> {len(orders_df)}")
        
        if orders_df.empty:
            print("No orders found in date range")
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    
    # Filter for orders with auction data if requested
    if auction_orders_only:
        original_count = len(orders_df)
        orders_df = orders_df[
            (orders_df['auctionDuration'] > 0) | 
            (orders_df['auctionStartPrice'].astype(float) != 0)
        ]
        print(f"Filtered for orders with auction data: {original_count} -> {len(orders_df)}")
        
        if orders_df.empty:
            print("No orders with auction data found after filtering.")
            return orders_df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    
    # Get the list of order IDs
    order_ids = orders_df['orderId'].astype(str).tolist()
    print(f"Found {len(order_ids)} orders. Fetching actions for each order...")
    
    # Fetch actions for each order
    all_actions = []
    for order_id in order_ids:
        try:
            # Get actions for this order
            order_actions_df = get_user_order_actions(user_public_key, order_id)
            
            if not order_actions_df.empty:
                # Add the orderId as a column for joining later
                order_actions_df['orderId'] = order_id
                all_actions.append(order_actions_df)
                print(f"Fetched {len(order_actions_df)} actions for order ID {order_id}")
            else:
                print(f"No actions found for order ID {order_id}")
                
            # Be nice to the API
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error fetching actions for order ID {order_id}: {e}")
    
    # Combine all actions into a single DataFrame
    if all_actions:
        actions_df = pd.concat(all_actions, ignore_index=True)
        print(f"Total actions fetched: {len(actions_df)}")
        
        # Create a joined DataFrame
        # Convert orderId to string in both DataFrames to ensure proper joining
        orders_df['orderId'] = orders_df['orderId'].astype(str)
        actions_df['orderId'] = actions_df['orderId'].astype(str)
        
        # Join the DataFrames
        joined_df = pd.merge(
            orders_df,
            actions_df,
            on='orderId',
            how='left',
            suffixes=('_order', '_action')
        )
        
        print(f"Created joined DataFrame with {len(joined_df)} rows")
        
        # Calculate auction slot difference for each order
        print("Calculating auction slot differences...")
        slot_diffs = []
        for order_id in order_ids:
            slot_diff = calculate_auction_slot_diff(actions_df, order_id)
            slot_diffs.append({
                'orderId': order_id,
                'auctionSlotDiff': slot_diff
            })
        
        # Create a new DataFrame with the slot differences
        auction_slot_diff_df = pd.DataFrame(slot_diffs)
        
        # Merge with the orders DataFrame to create the final result
        auction_slot_diff_df = pd.merge(
            orders_df,
            auction_slot_diff_df,
            on='orderId',
            how='left'
        )
        
        print(f"Created auction slot difference DataFrame with {len(auction_slot_diff_df)} rows")
        
        # After creating auction_slot_diff_df, create the simplified auction metrics DataFrame
        if not auction_slot_diff_df.empty:
            # Convert Unix timestamp to datetime and get the date range
            start_date = pd.to_datetime(auction_slot_diff_df['ts'].min(), unit='s').date()
            end_date = pd.to_datetime(auction_slot_diff_df['ts'].max(), unit='s').date()
            
            # Get trade data for the same user
            trades_df = get_user_trades(
                user_public_key=user_public_key,
                start_date=start_date,
                end_date=end_date
            )

            if not trades_df.empty:
                # Ensure order IDs are strings for joining
                trades_df['takerOrderId'] = trades_df['takerOrderId'].astype(str)
                auction_slot_diff_df['orderId'] = auction_slot_diff_df['orderId'].astype(str)

                # Join with trades to get oracle price
                auction_slot_diff_df = pd.merge(
                    auction_slot_diff_df,
                    trades_df[['takerOrderId', 'oraclePrice']],
                    left_on='orderId',
                    right_on='takerOrderId',
                    how='left'
                )

            # Calculate fillPrice and convert price columns as before
            auction_slot_diff_df['fillPrice'] = (
                auction_slot_diff_df['quoteAssetAmountFilled'].astype(float) / 
                auction_slot_diff_df['baseAssetAmountFilled'].astype(float)
            )
            
            # Convert price columns to float for calculations
            price_columns = ['auctionStartPrice', 'auctionEndPrice', 'oraclePrice']
            for col in price_columns:
                auction_slot_diff_df[col] = auction_slot_diff_df[col].astype(float)
            
            # Calculate absolute price differences
            auction_slot_diff_df['auctionStart_vs_fill'] = abs(auction_slot_diff_df['auctionStartPrice'] - auction_slot_diff_df['fillPrice'])
            auction_slot_diff_df['auctionEnd_vs_fill'] = abs(auction_slot_diff_df['auctionEndPrice'] - auction_slot_diff_df['fillPrice'])
            auction_slot_diff_df['oracle_vs_fill'] = abs(auction_slot_diff_df['oraclePrice'] - auction_slot_diff_df['fillPrice'])
            
            # Calculate bps differences (multiply by 10000 to convert to bps)
            auction_slot_diff_df['auctionStart_vs_fill_bps'] = abs((auction_slot_diff_df['auctionStartPrice'] - auction_slot_diff_df['fillPrice']) / auction_slot_diff_df['fillPrice'] * 10000)
            auction_slot_diff_df['auctionEnd_vs_fill_bps'] = abs((auction_slot_diff_df['auctionEndPrice'] - auction_slot_diff_df['fillPrice']) / auction_slot_diff_df['fillPrice'] * 10000)
            auction_slot_diff_df['oracle_vs_fill_bps'] = abs((auction_slot_diff_df['oraclePrice'] - auction_slot_diff_df['fillPrice']) / auction_slot_diff_df['fillPrice'] * 10000)
            
            # Create simplified DataFrame with selected columns in specific order
            auction_metrics_df = auction_slot_diff_df[[
                'orderId',
                'user',
                'auctionDuration',
                'auctionStartPrice',
                'auctionEndPrice',
                'fillPrice',
                'oraclePrice',
                'auctionStart_vs_fill',
                'auctionEnd_vs_fill',
                'oracle_vs_fill',
                'auctionStart_vs_fill_bps',
                'auctionEnd_vs_fill_bps',
                'oracle_vs_fill_bps',
                'auctionSlotDiff'
            ]].copy()
            
            print(f"Created auction metrics DataFrame with {len(auction_metrics_df)} rows")
            
            return orders_df.drop_duplicates(), actions_df.drop_duplicates(), joined_df.drop_duplicates(), auction_slot_diff_df.drop_duplicates(), auction_metrics_df.drop_duplicates()
        else:
            print("No auction metrics available - returning empty DataFrames")
            return orders_df.drop_duplicates(), actions_df.drop_duplicates(), joined_df.drop_duplicates(), pd.DataFrame(), pd.DataFrame()
    else:
        print("No actions found for any orders")
        # Return empty DataFrame for the auction_slot_diff_df as well
        return orders_df.drop_duplicates(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()