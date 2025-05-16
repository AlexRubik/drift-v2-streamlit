import time
from datetime import date, datetime

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


def get_user_orders(user_public_key: str, market_filter: str, symbol: str, pages_max: int = None):
    """
    Fetches order records for a specific user and market.
    
    Args:
        user_public_key: The public key of the user account
        market_filter: The market type ('spot', 'perp', or 'prediction')
        symbol: The market symbol (e.g., 'SOL-PERP', 'SOL')
        
    Returns:
        DataFrame containing order records sorted by lastUpdatedTs
    """
    print(f"Fetching orders for {user_public_key} in {market_filter} market {symbol}...")
    
    all_records = []
    next_page_token = None
    page_count = 1
    
    
    while pages_max is None or page_count < pages_max:
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
    
    # Convert timestamp columns to datetime
    timestamp_columns = ['ts', 'maxTs', 'lastUpdatedTs']
    for col in timestamp_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], unit='s')
    
    # Sort by lastUpdatedTs (newest first)
    if 'ts' in df.columns:
        df = df.sort_values('ts', ascending=False).reset_index(drop=True)
    
    print(f"Finished fetching orders. Total records: {len(df)}")
    return df


# @cache_data(ttl=60 * 15)
# def get_user_liquidations(user_public_key: Pubkey, start_date: date, end_date: date) -> pd.DataFrame:
#     # Assuming liquidations are less frequent, might need different handling or endpoint structure
#     return _fetch_user_records("liquidations", user_public_key, start_date, end_date)
