import datetime
import pandas as pd
import streamlit as st
from driftpy.drift_client import DriftClient
from datafetch.api_fetch import get_trades_for_range_pandas
from datafetch.s3_fetch import load_s3_trades_data
from constants import ALL_MARKET_NAMES
from driftpy.constants.perp_markets import mainnet_perp_market_configs
from driftpy.constants.spot_markets import mainnet_spot_market_configs
from datafetch.user_records import get_user_orders

async def process_taker_data(selected_market, start_date, end_date):
    print("processing taker data for", selected_market, start_date, end_date)
    all_trades_for_range_df = get_trades_for_range_pandas(selected_market, start_date, end_date)
    
    # grab all unique/deduped taker pubkeys from the taker column
    unique_taker_pubkeys = all_trades_for_range_df['taker'].unique()
    
    # Convert date objects to pandas datetime for comparison
    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)  # End of the day
    
    # for each taker pubkey, grab all orders
    for taker_pubkey in unique_taker_pubkeys:
        pages_max = 130
        if pages_max is not None:
            print("YOU ARE USING A LIMITED NUMBER OF PAGES, THIS IS NOT RECOMMENDED FOR PRODUCTION")
        # returns a df
        all_taker_orders = get_user_orders(taker_pubkey, 'perp', selected_market, pages_max=pages_max)
        # filter for "lastActionStatus": "filled"
        all_taker_orders = all_taker_orders[all_taker_orders['lastActionStatus'] == 'filled']
        print("new row count after filled filter:", len(all_taker_orders))
        
        # filter ts according to start_date and end_date
        all_taker_orders = all_taker_orders[(all_taker_orders['ts'] >= start_datetime) & 
                                           (all_taker_orders['ts'] <= end_datetime)]
        print("new row count after date filter:", len(all_taker_orders))
        if pages_max is not None:
            print("YOU ARE USING A LIMITED NUMBER OF PAGES, THIS IS NOT RECOMMENDED FOR PRODUCTION")
        return all_taker_orders #TODO: handle in a way where we move this outside of the loop
    


async def taker_execution_analysis(clearing_house: DriftClient):
    
    st.title("Taker Execution Analysis")
    
    # Create columns for inputs
    authority0, market_symbol0, date_col1, date_col2 = st.columns([10, 3, 3, 3])
    
    # Market selection using the same approach as in show_user_perf
    perp_markets = [m.symbol for m in mainnet_perp_market_configs]
    spot_markets = [m.symbol for m in mainnet_spot_market_configs]

    markets = []
    for perp in perp_markets:
        markets.append(perp)
        base_asset = perp.replace("-PERP", "")
        if base_asset in spot_markets:
            markets.append(base_asset)

    for spot in spot_markets:
        if spot not in markets:
            markets.append(spot)
            
    selected_market = market_symbol0.selectbox(
        "Market symbol", 
        markets, 
        index=markets.index("SOL-PERP")
    )
    
    # Date range selection
    latest_date = pd.to_datetime(datetime.datetime.now(), utc=True)
    start_date = date_col1.date_input(
        "Start date:",
        latest_date - datetime.timedelta(days=1),
        min_value=datetime.datetime(2022, 11, 4),
        max_value=latest_date,
    )
    
    end_date = date_col2.date_input(
        "End date:",
        latest_date,
        min_value=datetime.datetime(2022, 11, 4),
        max_value=latest_date,
    )
    
    # Fetch data button
    if st.button("Fetch Data"):
        with st.spinner(f"Fetching trade data for {selected_market} from {start_date} to {end_date}..."):
            try:
                # Fetch trade data using the API without page parameter to get all data
                #TODO: filter out bad orders like no taker value/reverted fills?
                trades_df = await process_taker_data(selected_market, start_date, end_date)
                
                if trades_df.empty:
                    st.warning(f"No trade data found for {selected_market} in the selected date range.")
                    return
                
                # Display basic info
                st.success(f"Fetched {len(trades_df)} trades for {selected_market}")
                
                # Display the data in a table
                st.subheader("Trade Data")
                st.dataframe(trades_df)
                
            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("Try selecting a different date range or market where data is available.")
