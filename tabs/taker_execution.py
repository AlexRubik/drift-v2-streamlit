import datetime
import pandas as pd
import streamlit as st
from driftpy.drift_client import DriftClient
from datafetch.api_fetch import get_trades_for_range_pandas
from datafetch.s3_fetch import load_s3_trades_data
from constants import ALL_MARKET_NAMES
from driftpy.constants.perp_markets import mainnet_perp_market_configs
from driftpy.constants.spot_markets import mainnet_spot_market_configs
from datafetch.user_records import analyze_auction_slots_by_direction, format_auction_analysis_results, get_user_orders, get_user_order_actions, get_user_orders_and_actions
from datafetch.transaction_fetch import get_slot_for_tx
import plotly.express as px

async def getSlot():
    tx_sig = '28nwj4mKK2M7YxmK12fK24k7U6mcuurSHaN2cC5pxPqiwtXsU9ruyuFGT2XvVSnrVDzGV8xRojQKAm9U5RjqgfwQ'
    
    try:
        slot = await get_slot_for_tx(tx_sig)
        print(f"Transaction {tx_sig} was included in slot {slot}")
        return slot
    except Exception as e:
        print(f"Error getting slot for transaction: {str(e)}")

async def process_taker_data(taker_pubkey, selected_market, start_date: datetime.date, end_date: datetime.date, order_type=None):
    print("processing taker data for", taker_pubkey, selected_market, start_date, end_date)
    if order_type:
        if isinstance(order_type, list):
            print(f"Filtering for order types: {', '.join(order_type)}")
        else:
            print(f"Filtering for order type: {order_type}")

    # Convert date objects to pandas datetime for comparison
    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)  # End of the day
    
    pages_max = 20
    if pages_max is not None:
        # we limit number of pages, otherwise we spend a lot of time fetching ALL of the user's orders
        print("YOU ARE USING A LIMITED NUMBER OF PAGES, THIS IS NOT RECOMMENDED FOR PRODUCTION")
    
    # Get orders, actions, and joined data
    orders_df, actions_df, joined_orders_and_actions_df, auction_slot_diff_orders_df, auction_metrics_df = get_user_orders_and_actions(
        taker_pubkey, 
        'perp', 
        selected_market, 
        start_date,
        end_date,
        pages_max=pages_max, 
        auction_orders_only=True,
        last_action_status='filled',
        order_type=order_type,
        exclude_liquidations=True
    )
    
    # Filter by date range using the appropriate timestamp column
    if not joined_orders_and_actions_df.empty:
        # Check which timestamp column exists in the joined dataframe
        ts_column = 'ts_order' if 'ts_order' in joined_orders_and_actions_df.columns else 'ts'
        
        # Filter by date
        joined_orders_and_actions_df = joined_orders_and_actions_df[
            (joined_orders_and_actions_df[ts_column] >= start_datetime) & 
            (joined_orders_and_actions_df[ts_column] <= end_datetime)
        ]
        print("new row count after date filter:", len(joined_orders_and_actions_df))
    
    if pages_max is not None:
        # we limit number of pages, otherwise we spend a lot of time fetching ALL of the user's orders
        print("YOU ARE USING A LIMITED NUMBER OF PAGES, THIS IS NOT RECOMMENDED FOR PRODUCTION")
    
    return orders_df, actions_df, joined_orders_and_actions_df, auction_slot_diff_orders_df, auction_metrics_df



def slot_stats(orders_with_slot_diff_df):
    # mean, median, min, max, quantile
    slot_diff = orders_with_slot_diff_df['auctionSlotDiff']
    mean_slot_diff = slot_diff.mean()
    median_slot_diff = slot_diff.median()
    min_slot_diff = slot_diff.min()
    max_slot_diff = slot_diff.max()
    q1_slot_diff = slot_diff.quantile(0.25) # Q1
    q3_slot_diff = slot_diff.quantile(0.75) # Q3
    return mean_slot_diff, median_slot_diff, min_slot_diff, max_slot_diff, q1_slot_diff, q3_slot_diff

def price_diff_stats(metrics_df: pd.DataFrame):
    """Calculate statistics for price difference fields and return as DataFrames"""
    # Define the fields for each type of difference
    abs_diff_fields = [
        'auctionStart_vs_fill',
        'auctionEnd_vs_fill',
        'oracle_vs_fill'
    ]
    
    bps_diff_fields = [
        'auctionStart_vs_fill_bps',
        'auctionEnd_vs_fill_bps',
        'oracle_vs_fill_bps'
    ]
    
    # Calculate stats for absolute differences
    abs_stats = {}
    for field in abs_diff_fields:
        series = metrics_df[field]
        abs_stats[field] = {
            'mean': series.mean(),
            'std': series.std(),
            'min': series.min(),
            'q1': series.quantile(0.25),
            'median': series.median(),
            'q3': series.quantile(0.75),
            'max': series.max()
        }
    
    # Calculate stats for BPS differences
    bps_stats = {}
    for field in bps_diff_fields:
        series = metrics_df[field]
        bps_stats[field] = {
            'mean': series.mean(),
            'std': series.std(),
            'min': series.min(),
            'q1': series.quantile(0.25),
            'median': series.median(),
            'q3': series.quantile(0.75),
            'max': series.max()
        }
    
    # Convert to DataFrames
    abs_df = pd.DataFrame(abs_stats).round(4)
    bps_df = pd.DataFrame(bps_stats).round(2)
    
    # Rename columns for better readability
    abs_df.columns = ['Auction Start vs Fill', 'Auction End vs Fill', 'Oracle vs Fill']
    bps_df.columns = ['Auction Start vs Fill', 'Auction End vs Fill', 'Oracle vs Fill']
    
    return abs_df, bps_df

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
            
    # taker pubkey input
    taker_pubkey = st.text_input("Taker pubkey", value="48TRXHqSoBUYTRUvPyPorZQPiNSdAQEg8J6b7Kepmbzh")
            
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
    
    # Add order type multi-select filter
    order_types = ["limit", "market", "oracle", "triggerLimit", "triggerMarket"]
    selected_order_types = st.multiselect(
        "Order Types (select none for all types)", 
        order_types,
        default=["limit", "market"]
    )
    
    # Convert empty selection to None for the filter
    order_type_filter = selected_order_types if selected_order_types else None
    
    # Add order ID input for fetching order actions
    order_id = st.text_input("Order ID (only used for Fetch Order Actions)", value="20775")
    
    # Create columns for the buttons
    col1, col2, col3 = st.columns(3)
    
    # Fetch data button
    if col1.button("Fetch Orders"):
        with st.spinner(f"Fetching orders and actions data for {selected_market} from {start_date} to {end_date}..."):
            try:
                orders_df, actions_df, taker_df, auction_slot_diff_orders_df, auction_metrics_df = await process_taker_data(
                    taker_pubkey, 
                    selected_market, 
                    start_date, 
                    end_date,
                    order_type=order_type_filter
                )
                
                if taker_df.empty:
                    st.warning(f"No trade data found for {selected_market} in the selected date range.")
                    return
                
                # Display basic info
                st.success(f"Fetched {len(taker_df)} taker orders for {selected_market}")
                
                # Display the DataFrames (original code)
                st.subheader("Auction Metrics")
                st.dataframe(auction_metrics_df)
                
                st.subheader("Orders + Auction Metrics")
                st.dataframe(auction_slot_diff_orders_df)
                
                if not auction_slot_diff_orders_df.empty:
                    mean_slot_diff, median_slot_diff, min_slot_diff, max_slot_diff, q1_slot_diff, q3_slot_diff = slot_stats(auction_slot_diff_orders_df)
                    st.write("Slot Diff Stats")
                    st.write(f"Mean: {int(mean_slot_diff)}, Median: {int(median_slot_diff)}, Min: {int(min_slot_diff)}, Max: {int(max_slot_diff)}, Q1: {int(q1_slot_diff)}, Q3: {int(q3_slot_diff)}")
                else:
                    st.info("No orders with auction slot diff data available.")
                    
                # Get the analysis results
                analysis_results = analyze_auction_slots_by_direction(auction_slot_diff_orders_df)

                # Format the results
                formatted_results = format_auction_analysis_results(analysis_results)

                # Display the results
                display_auction_analysis(formatted_results)
                
                
                # TODO: output doesn't look right, need to fix
                # st.subheader("Orders joined with actions")
                # st.dataframe(taker_df)
                
                # Price Comparison Chart
                st.subheader("Price Comparison")
                
                # Convert price columns to float
                price_columns = ['auctionStartPrice', 'auctionEndPrice', 'fillPrice', 'oraclePrice']
                for col in price_columns:
                    auction_slot_diff_orders_df[col] = auction_slot_diff_orders_df[col].astype(float)
                
                # Create the line chart
                fig = px.line(
                    auction_slot_diff_orders_df,
                    x=auction_slot_diff_orders_df['ts'], # ts for each order
                    y=price_columns,
                    title=f'Price Comparison for {selected_market}',
                    labels={
                        'index': 'Timestamp',
                        'value': 'Price',
                        'variable': 'Price Type'
                    }
                )
                
                # Customize the layout
                fig.update_layout(
                    xaxis_title="Timestamp",
                    yaxis_title="Price",
                    legend_title="Price Type",
                    hovermode='x unified'
                )
                
                # Display the chart
                st.plotly_chart(fig, use_container_width=True)
                
                # Calculate and display price difference statistics
                abs_stats_df, bps_stats_df = price_diff_stats(auction_metrics_df)
                
                st.subheader("Price Difference Statistics")
                
                # Display absolute difference stats
                st.write("Absolute Price Differences:")
                st.dataframe(abs_stats_df)
                
                # Display BPS difference stats
                st.write("BPS Differences:")
                st.dataframe(bps_stats_df)

            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("Try selecting a different date range or market where data is available.")
    
    # Fetch order actions button            
    if col2.button("Fetch Order Actions"):
        with st.spinner(f"Fetching actions for order ID {order_id}..."):
            try:
                # Fetch order actions
                actions_df = get_user_order_actions(taker_pubkey, order_id)
                
                if actions_df.empty:
                    st.warning(f"No actions found for order ID {order_id}.")
                    return
                
                # Display basic info
                st.success(f"Fetched {len(actions_df)} actions for order ID {order_id}")
                
                # Display the data in a table
                st.subheader("Order Actions")
                st.dataframe(actions_df)
            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("Try checking if the order ID exists for this user.")
                
    # Get slot button
    if col3.button("Get Slot"):
        with st.spinner("Getting slot..."):
            slot = await getSlot()
            st.success(f"Slot: {slot}")

def display_auction_analysis(formatted_results):
    st.header("Auction Slot Difference Analysis")

    # Overall Statistics
    st.subheader("Overall Statistics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("LONG Orders (All Types)")
        st.table(pd.Series(formatted_results['overall_stats']['long']['basic_stats']))
        if formatted_results['overall_stats']['long']['outliers']:
            st.write("Outliers:")
            st.table(pd.DataFrame(formatted_results['overall_stats']['long']['outliers']))
    
    with col2:
        st.write("SHORT Orders (All Types)")
        st.table(pd.Series(formatted_results['overall_stats']['short']['basic_stats']))
        if formatted_results['overall_stats']['short']['outliers']:
            st.write("Outliers:")
            st.table(pd.DataFrame(formatted_results['overall_stats']['short']['outliers']))
    
    st.write("Overall Comparison (Long vs Short)")
    st.table(pd.Series(formatted_results['overall_stats']['comparison']))
    
    # Statistics by Order Type
    st.subheader("Statistics by Order Type")
    
    for order_type, type_results in formatted_results['by_order_type'].items():
        st.write(f"\nORDER TYPE: {order_type}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("LONG Orders")
            st.table(pd.Series(type_results['long']['basic_stats']))
            if type_results['long']['outliers']:
                st.write("Outliers:")
                st.table(pd.DataFrame(type_results['long']['outliers']))
        
        with col2:
            st.write("SHORT Orders")
            st.table(pd.Series(type_results['short']['basic_stats']))
            if type_results['short']['outliers']:
                st.write("Outliers:")
                st.table(pd.DataFrame(type_results['short']['outliers']))
        
        st.write(f"Comparison for {order_type} (Long vs Short)")
        st.table(pd.Series(type_results['comparison']))
