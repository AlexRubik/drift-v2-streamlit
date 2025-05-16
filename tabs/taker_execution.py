import datetime
import pandas as pd
import streamlit as st
from driftpy.drift_client import DriftClient
from datafetch.api_fetch import get_trades_for_range_pandas
from datafetch.s3_fetch import load_s3_trades_data
from constants import ALL_MARKET_NAMES
from driftpy.constants.perp_markets import mainnet_perp_market_configs
from driftpy.constants.spot_markets import mainnet_spot_market_configs


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
                trades_df = get_trades_for_range_pandas(selected_market, start_date, end_date)
                
                if trades_df.empty:
                    st.warning(f"No trade data found for {selected_market} in the selected date range.")
                    return
                
                # Display basic info
                st.success(f"Fetched {len(trades_df)} trades for {selected_market}")
                
                # Display the data in a table
                st.subheader("Trade Data")
                st.dataframe(trades_df)
                
                # Show some basic statistics
                st.subheader("Basic Statistics")
                
                # Create columns for statistics
                stat_cols = st.columns(3)
                
                # Display total volume if available
                if 'quoteAssetAmountFilled' in trades_df.columns:
                    volume = pd.to_numeric(trades_df['quoteAssetAmountFilled'], errors='coerce').sum()
                    stat_cols[0].metric("Total Volume", f"${volume:,.2f}")
                
                # Display trade count
                stat_cols[1].metric("Trade Count", f"{len(trades_df):,}")
                
            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("Try selecting a different date range or market where data is available.")
