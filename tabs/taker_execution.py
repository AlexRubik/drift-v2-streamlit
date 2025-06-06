import datetime
import pandas as pd
import streamlit as st
from driftpy.drift_client import DriftClient
from datafetch.api_fetch import get_trades_for_range_pandas
from datafetch.s3_fetch import load_s3_trades_data
from constants import ALL_MARKET_NAMES
from driftpy.constants.perp_markets import mainnet_perp_market_configs
from driftpy.constants.spot_markets import mainnet_spot_market_configs
from datafetch.user_records import analyze_auction_slots_by_direction, format_auction_analysis_results, get_user_orders, get_user_order_actions, get_user_orders_and_actions, get_multiple_users_orders_and_actions, analyze_auction_price_differences_by_direction
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

async def process_taker_data(taker_pubkeys, selected_market, start_date: datetime.date, end_date: datetime.date, order_type=None):
    print("processing taker data for", taker_pubkeys, selected_market, start_date, end_date)
    if order_type:
        if isinstance(order_type, list):
            print(f"Filtering for order types: {', '.join(order_type)}")
        else:
            print(f"Filtering for order type: {order_type}")

    # Convert date objects to pandas datetime for comparison
    start_datetime = pd.to_datetime(start_date)
    end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)  # End of the day
    
    pages_max = 10
    if pages_max is not None:
        # we limit number of pages, otherwise we spend a lot of time fetching ALL of the user's orders
        print("YOU ARE USING A LIMITED NUMBER OF PAGES, THIS IS NOT RECOMMENDED FOR PRODUCTION")
    
    # Get orders, actions, and joined data for multiple users
    orders_df, actions_df, joined_orders_and_actions_df, auction_slot_diff_orders_df, auction_metrics_df = get_multiple_users_orders_and_actions(
        taker_pubkeys, 
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
            
    # taker pubkeys input - changed to text_area for multiple pubkeys
    st.subheader("Taker Public Keys")
    taker_pubkeys_input = st.text_area(
        "Enter taker pubkeys (one per line)", 
        value="48TRXHqSoBUYTRUvPyPorZQPiNSdAQEg8J6b7Kepmbzh",
        height=100,
        help="Enter one public key per line. You can add multiple users to analyze their combined data."
    )
    
    # Parse the pubkeys from the text area
    taker_pubkeys = [pubkey.strip() for pubkey in taker_pubkeys_input.strip().split('\n') if pubkey.strip()]
    
    # Display how many pubkeys were entered
    if taker_pubkeys:
        st.info(f"Found {len(taker_pubkeys)} taker pubkey(s) to analyze")
        with st.expander("View entered pubkeys"):
            for i, pubkey in enumerate(taker_pubkeys, 1):
                st.write(f"{i}. {pubkey}")
    else:
        st.warning("Please enter at least one taker pubkey")
            
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
    
    # Add order ID input for fetching order actions (keep single user functionality)
    st.subheader("Single Order Analysis")
    col_single_1, col_single_2 = st.columns(2)
    single_taker_pubkey = col_single_1.text_input("Single taker pubkey (for order actions)", value="48TRXHqSoBUYTRUvPyPorZQPiNSdAQEg8J6b7Kepmbzh")
    order_id = col_single_2.text_input("Order ID (only used for Fetch Order Actions)", value="20775")
    
    # Create columns for the buttons
    col1, col2, col3 = st.columns(3)
    
    # Fetch data button
    if col1.button("Fetch Orders"):
        if not taker_pubkeys:
            st.error("Please enter at least one taker pubkey")
            return
            
        with st.spinner(f"Fetching orders and actions data for {len(taker_pubkeys)} user(s) in {selected_market} from {start_date} to {end_date}..."):
            try:
                orders_df, actions_df, taker_df, auction_slot_diff_orders_df, auction_metrics_df = await process_taker_data(
                    taker_pubkeys, 
                    selected_market, 
                    start_date, 
                    end_date,
                    order_type=order_type_filter
                )
                
                if taker_df.empty:
                    st.warning(f"No trade data found for {selected_market} in the selected date range.")
                    return
                
                # Display basic info
                st.success(f"Fetched {len(taker_df)} taker orders for {selected_market} from {len(taker_pubkeys)} user(s)")
                
                # Display summary by user
                if 'user' in auction_slot_diff_orders_df.columns:
                    user_summary = auction_slot_diff_orders_df.groupby('user').size().reset_index(name='order_count')
                    st.subheader("Orders by User")
                    st.dataframe(user_summary)
                
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
                
# Auction Slot Difference Dot Plot
                st.subheader("Auction Slot Difference Over Time")
                
                # Create dot plot for auction slot differences
                slot_fig = px.scatter(
                    auction_slot_diff_orders_df,
                    x='ts',
                    y='auctionSlotDiff',
                    color='direction',  # Color by long/short direction
                    hover_data={
                        'orderId': True,
                        'user': True,
                        'orderType': True,
                        'auctionDuration': True,
                        'fillPrice': ':.4f',
                        'auctionStartPrice': ':.4f',
                        'auctionEndPrice': ':.4f',
                        'baseAssetAmountFilled': True,
                        'ts': '|%Y-%m-%d %H:%M:%S'
                    },
                    title=f'Auction Slot Differences Over Time for {selected_market}',
                    labels={
                        'ts': 'Timestamp',
                        'auctionSlotDiff': 'Auction Slot Difference',
                        'direction': 'Order Direction'
                    }
                )
                
                # Customize the layout
                slot_fig.update_layout(
                    xaxis_title="Timestamp",
                    yaxis_title="Auction Slot Difference",
                    legend_title="Order Direction",
                    hovermode='closest'
                )
                
                # Add horizontal line at median slot difference for reference
                median_slot_diff = auction_slot_diff_orders_df['auctionSlotDiff'].median()
                slot_fig.add_hline(
                    y=median_slot_diff, 
                    line_dash="dash", 
                    line_color="gray",
                    annotation_text=f"Median: {median_slot_diff:.0f} slots"
                )
                
                # Display the slot difference chart
                st.plotly_chart(slot_fig, use_container_width=True)
                
                # Price Comparison Chart
                st.subheader("Price Comparison")
                
                # price difference analysis by direction
                price_diff_results = analyze_auction_price_differences_by_direction(auction_slot_diff_orders_df)
                display_price_difference_analysis(price_diff_results)
                
                # Convert price columns to float
                price_columns = ['auctionStartPrice', 'auctionEndPrice', 'fillPrice', 'oraclePrice']
                for col in price_columns:
                    auction_slot_diff_orders_df[col] = auction_slot_diff_orders_df[col].astype(float)
                
                # Reshape data for proper line plotting
                # Create a copy of the dataframe with only the columns we need
                price_data = auction_slot_diff_orders_df[['ts', 'orderId', 'user', 'orderType', 'direction'] + price_columns].copy()
                
                # Melt the dataframe to long format
                price_data_melted = pd.melt(
                    price_data,
                    id_vars=['ts', 'orderId', 'user', 'orderType', 'direction'],
                    value_vars=price_columns,
                    var_name='Price Type',
                    value_name='Price'
                )
                
                # Sort by timestamp to ensure proper line connections
                price_data_melted = price_data_melted.sort_values('ts')
                
                # Create the line chart with melted data
                fig = px.line(
                    price_data_melted,
                    x='ts',
                    y='Price',
                    color='Price Type',
                    title=f'Price Comparison for {selected_market} ({len(taker_pubkeys)} user(s))',
                    labels={
                        'ts': 'Timestamp',
                        'Price': 'Price',
                        'Price Type': 'Price Type'
                    },
                    hover_data={
                        'orderId': True,
                        'user': True,
                        'orderType': True,
                        'direction': True,
                        'Price': ':.4f',
                        'ts': '|%Y-%m-%d %H:%M:%S'
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
    
    # Fetch order actions button (keep single user functionality)           
    if col2.button("Fetch Order Actions"):
        if not single_taker_pubkey.strip():
            st.error("Please enter a single taker pubkey for order actions")
            return
            
        with st.spinner(f"Fetching actions for order ID {order_id}..."):
            try:
                # Fetch order actions
                actions_df = get_user_order_actions(single_taker_pubkey, order_id)
                
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
        # Convert to DataFrame with proper handling of data types
        long_stats = pd.DataFrame(list(formatted_results['overall_stats']['long']['basic_stats'].items()), 
                                 columns=['Metric', 'Value'])
        st.dataframe(long_stats)
        
        if formatted_results['overall_stats']['long']['outliers']:
            st.write("Outliers:")
            outliers_df = pd.DataFrame(formatted_results['overall_stats']['long']['outliers'])
            st.dataframe(outliers_df)
    
    with col2:
        st.write("SHORT Orders (All Types)")
        # Convert to DataFrame with proper handling of data types
        short_stats = pd.DataFrame(list(formatted_results['overall_stats']['short']['basic_stats'].items()), 
                                  columns=['Metric', 'Value'])
        st.dataframe(short_stats)
        
        if formatted_results['overall_stats']['short']['outliers']:
            st.write("Outliers:")
            outliers_df = pd.DataFrame(formatted_results['overall_stats']['short']['outliers'])
            st.dataframe(outliers_df)
    
    st.write("Overall Comparison (Long vs Short)")
    # Convert to DataFrame with proper handling of data types
    comparison_stats = pd.DataFrame(list(formatted_results['overall_stats']['comparison'].items()), 
                                   columns=['Metric', 'Value'])
    st.dataframe(comparison_stats)

    # Statistics by Order Type
    st.subheader("Statistics by Order Type")
    
    for order_type, type_results in formatted_results['by_order_type'].items():
        st.write(f"\nORDER TYPE: {order_type}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("LONG Orders")
            long_stats = pd.DataFrame(list(type_results['long']['basic_stats'].items()), 
                                     columns=['Metric', 'Value'])
            st.dataframe(long_stats)
            
            if type_results['long']['outliers']:
                st.write("Outliers:")
                outliers_df = pd.DataFrame(type_results['long']['outliers'])
                st.dataframe(outliers_df)
        
        with col2:
            st.write("SHORT Orders")
            short_stats = pd.DataFrame(list(type_results['short']['basic_stats'].items()), 
                                      columns=['Metric', 'Value'])
            st.dataframe(short_stats)
            
            if type_results['short']['outliers']:
                st.write("Outliers:")
                outliers_df = pd.DataFrame(type_results['short']['outliers'])
                st.dataframe(outliers_df)
        
        st.write(f"Comparison for {order_type} (Long vs Short)")
        comparison_stats = pd.DataFrame(list(type_results['comparison'].items()), 
                                       columns=['Metric', 'Value'])
        st.dataframe(comparison_stats)

def display_price_difference_analysis(price_diff_results):
    """Display the price difference analysis results in Streamlit"""
    st.header("Price Difference Analysis by Direction")
    
    # Helper function to safely format numeric values
    def safe_format(value, format_str=".2f", suffix=""):
        """Safely format a value that might be None, string, or numeric"""
        if value is None:
            return "N/A"
        if isinstance(value, str):
            return value
        try:
            return f"{float(value):{format_str}}{suffix}"
        except (ValueError, TypeError):
            return str(value)
    
    # Summary section
    st.subheader("Summary")
    summary = price_diff_results.get('summary', {})
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Orders", summary.get('total_orders', 0))
    with col2:
        st.metric("Long Orders", f"{summary.get('long_orders_count', 0)} ({safe_format(summary.get('long_orders_pct', 0), '.1f')}%)")
    with col3:
        st.metric("Short Orders", f"{summary.get('short_orders_count', 0)} ({safe_format(summary.get('short_orders_pct', 0), '.1f')}%)")
    
    # Long vs Short Analysis
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("LONG Orders Analysis")
        long_analysis = price_diff_results.get('long_analysis', {})
        
        if 'oracle_deviation' in long_analysis:
            oracle_data = long_analysis['oracle_deviation']
            st.write("**Oracle Deviation Analysis:**")
            
            # Create metrics with tooltips
            quality_col, avg_col = st.columns(2)
            with quality_col:
                st.metric(
                    "Quality", 
                    oracle_data.get('oracle_deviation_quality', 'N/A'),
                    help="Overall quality rating based on average oracle deviation: EXCELLENT (<10 bps), GOOD (<25 bps), FAIR (<50 bps), POOR (>50 bps). Lower deviations indicate better price discovery."
                )
            with avg_col:
                st.metric(
                    "Avg Deviation", 
                    safe_format(oracle_data.get('avg_oracle_deviation_bps', 0), '.2f', ' bps'),
                    help="Average absolute difference between fill price and oracle price in basis points. Lower values indicate fills closer to fair market value."
                )
            
            median_col, within10_col = st.columns(2)
            with median_col:
                st.metric(
                    "Median Deviation", 
                    safe_format(oracle_data.get('median_oracle_deviation_bps', 0), '.2f', ' bps'),
                    help="Middle value of oracle deviations when sorted. Less sensitive to outliers than average, shows typical performance."
                )
            with within10_col:
                st.metric(
                    "Within 10 bps", 
                    safe_format(oracle_data.get('close_to_oracle_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled within 10 basis points of oracle price. Higher percentages indicate tighter price discovery."
                )
            
            st.metric(
                "Within 25 bps", 
                safe_format(oracle_data.get('reasonable_from_oracle_pct', 0), '.1f', '%'),
                help="Percentage of orders that filled within 25 basis points of oracle price. Reasonable threshold for acceptable price discovery."
            )
            
            # Display oracle deviation outliers if any
            if 'oracle_deviation_outliers' in oracle_data and oracle_data['oracle_deviation_outliers']:
                st.write("**Oracle Deviation Outliers:**")
                outliers_df = pd.DataFrame(oracle_data['oracle_deviation_outliers'])
                st.dataframe(outliers_df, use_container_width=True)
        
        if 'auction_aggressiveness' in long_analysis:
            agg_data = long_analysis['auction_aggressiveness']
            st.write("**Auction Aggressiveness:**")
            
            tendency_col, strength_col = st.columns(2)
            with tendency_col:
                st.metric(
                    "Tendency", 
                    agg_data.get('tendency', 'N/A'),
                    help="Overall auction behavior: PASSIVE (fills closer to start price), AGGRESSIVE (fills closer to end price), or BALANCED. Indicates if auctions are too conservative or aggressive."
                )
            with strength_col:
                st.metric(
                    "Strength", 
                    safe_format(agg_data.get('tendency_strength_pct', 0), '.1f', '%'),
                    help="How pronounced the tendency is. Higher percentages indicate stronger directional bias in auction behavior."
                )
            
            start_col, end_col = st.columns(2)
            with start_col:
                st.metric(
                    "Closer to Start", 
                    safe_format(agg_data.get('closer_to_start_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled closer to auction start price than end price. High values suggest passive/conservative auctions."
                )
            with end_col:
                st.metric(
                    "Closer to End", 
                    safe_format(agg_data.get('closer_to_end_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled closer to auction end price than start price. High values suggest aggressive auctions."
                )
            
            dist_start_col, dist_end_col = st.columns(2)
            with dist_start_col:
                st.metric(
                    "Avg Distance to Start", 
                    safe_format(agg_data.get('avg_distance_to_start', 0), '.4f'),
                    help="Average absolute price difference between fill price and auction start price. Lower values indicate fills closer to initial auction price."
                )
            with dist_end_col:
                st.metric(
                    "Avg Distance to End", 
                    safe_format(agg_data.get('avg_distance_to_end', 0), '.4f'),
                    help="Average absolute price difference between fill price and auction end price. Lower values indicate fills closer to final auction price."
                )
    
    with col2:
        st.subheader("SHORT Orders Analysis")
        short_analysis = price_diff_results.get('short_analysis', {})
        
        if 'oracle_deviation' in short_analysis:
            oracle_data = short_analysis['oracle_deviation']
            st.write("**Oracle Deviation Analysis:**")
            
            # Create metrics with tooltips
            quality_col, avg_col = st.columns(2)
            with quality_col:
                st.metric(
                    "Quality", 
                    oracle_data.get('oracle_deviation_quality', 'N/A'),
                    help="Overall quality rating based on average oracle deviation: EXCELLENT (<10 bps), GOOD (<25 bps), FAIR (<50 bps), POOR (>50 bps). Lower deviations indicate better price discovery."
                )
            with avg_col:
                st.metric(
                    "Avg Deviation", 
                    safe_format(oracle_data.get('avg_oracle_deviation_bps', 0), '.2f', ' bps'),
                    help="Average absolute difference between fill price and oracle price in basis points. Lower values indicate fills closer to fair market value."
                )
            
            median_col, within10_col = st.columns(2)
            with median_col:
                st.metric(
                    "Median Deviation", 
                    safe_format(oracle_data.get('median_oracle_deviation_bps', 0), '.2f', ' bps'),
                    help="Middle value of oracle deviations when sorted. Less sensitive to outliers than average, shows typical performance."
                )
            with within10_col:
                st.metric(
                    "Within 10 bps", 
                    safe_format(oracle_data.get('close_to_oracle_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled within 10 basis points of oracle price. Higher percentages indicate tighter price discovery."
                )
            
            st.metric(
                "Within 25 bps", 
                safe_format(oracle_data.get('reasonable_from_oracle_pct', 0), '.1f', '%'),
                help="Percentage of orders that filled within 25 basis points of oracle price. Reasonable threshold for acceptable price discovery."
            )
            
            # Display oracle deviation outliers if any
            if 'oracle_deviation_outliers' in oracle_data and oracle_data['oracle_deviation_outliers']:
                st.write("**Oracle Deviation Outliers:**")
                outliers_df = pd.DataFrame(oracle_data['oracle_deviation_outliers'])
                st.dataframe(outliers_df, use_container_width=True)
        
        if 'auction_aggressiveness' in short_analysis:
            agg_data = short_analysis['auction_aggressiveness']
            st.write("**Auction Aggressiveness:**")
            
            tendency_col, strength_col = st.columns(2)
            with tendency_col:
                st.metric(
                    "Tendency", 
                    agg_data.get('tendency', 'N/A'),
                    help="Overall auction behavior: PASSIVE (fills closer to start price), AGGRESSIVE (fills closer to end price), or BALANCED. Indicates if auctions are too conservative or aggressive."
                )
            with strength_col:
                st.metric(
                    "Strength", 
                    safe_format(agg_data.get('tendency_strength_pct', 0), '.1f', '%'),
                    help="How pronounced the tendency is. Higher percentages indicate stronger directional bias in auction behavior."
                )
            
            start_col, end_col = st.columns(2)
            with start_col:
                st.metric(
                    "Closer to Start", 
                    safe_format(agg_data.get('closer_to_start_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled closer to auction start price than end price. High values suggest passive/conservative auctions."
                )
            with end_col:
                st.metric(
                    "Closer to End", 
                    safe_format(agg_data.get('closer_to_end_pct', 0), '.1f', '%'),
                    help="Percentage of orders that filled closer to auction end price than start price. High values suggest aggressive auctions."
                )
            
            dist_start_col, dist_end_col = st.columns(2)
            with dist_start_col:
                st.metric(
                    "Avg Distance to Start", 
                    safe_format(agg_data.get('avg_distance_to_start', 0), '.4f'),
                    help="Average absolute price difference between fill price and auction start price. Lower values indicate fills closer to initial auction price."
                )
            with dist_end_col:
                st.metric(
                    "Avg Distance to End", 
                    safe_format(agg_data.get('avg_distance_to_end', 0), '.4f'),
                    help="Average absolute price difference between fill price and auction end price. Lower values indicate fills closer to final auction price."
                )
    
    # Comparison section
    st.subheader("Long vs Short Comparison")
    comparison = price_diff_results.get('comparison', {})
    if comparison:
        bias_col, long_oracle_col, short_oracle_col = st.columns(3)
        
        with bias_col:
            st.metric(
                "Directional Bias", 
                comparison.get('directional_bias', 'N/A'),
                help="Which direction (LONG_FAVORED or SHORT_FAVORED) has better oracle price accuracy on average. Indicates if auction parameters should be asymmetric."
            )
        with long_oracle_col:
            st.metric(
                "Long Avg Oracle Deviation", 
                safe_format(comparison.get('long_oracle_avg_bps', 0), '.2f', ' bps'),
                help="Average oracle deviation for long orders only. Compare with short orders to identify directional performance differences."
            )
        with short_oracle_col:
            st.metric(
                "Short Avg Oracle Deviation", 
                safe_format(comparison.get('short_oracle_avg_bps', 0), '.2f', ' bps'),
                help="Average oracle deviation for short orders only. Compare with long orders to identify directional performance differences."
            )
        
        diff_col, accuracy_col = st.columns(2)
        with diff_col:
            st.metric(
                "Oracle Deviation Difference", 
                safe_format(comparison.get('oracle_deviation_diff_bps', 0), '.2f', ' bps'),
                help="Difference between long and short average oracle deviations (Long - Short). Positive values mean longs deviate more from oracle; negative means shorts deviate more."
            )
        with accuracy_col:
            st.metric(
                "Long More Accurate to Oracle", 
                str(comparison.get('long_more_accurate_to_oracle', False)),
                help="Whether long orders have lower average oracle deviation than short orders. True indicates long orders achieve better price discovery."
            )
    
    # Key insights section
    st.subheader("Key Insights")
    insights = []
    
    # Generate insights based on the analysis
    if 'long_analysis' in price_diff_results and 'short_analysis' in price_diff_results:
        long_oracle = price_diff_results['long_analysis'].get('oracle_deviation', {})
        short_oracle = price_diff_results['short_analysis'].get('oracle_deviation', {})
        
        long_quality = long_oracle.get('oracle_deviation_quality', 'UNKNOWN')
        short_quality = short_oracle.get('oracle_deviation_quality', 'UNKNOWN')
        
        if long_quality != short_quality:
            insights.append(f"📊 **Directional Performance Difference**: Long orders have {long_quality} oracle deviation quality while short orders have {short_quality}")
        
        long_agg = price_diff_results['long_analysis'].get('auction_aggressiveness', {})
        short_agg = price_diff_results['short_analysis'].get('auction_aggressiveness', {})
        
        long_tendency = long_agg.get('tendency', '')
        short_tendency = short_agg.get('tendency', '')
        
        if 'PASSIVE' in long_tendency and 'AGGRESSIVE' in short_tendency:
            insights.append("⚖️ **Asymmetric Behavior**: Long orders tend to be more passive while short orders are more aggressive")
        elif 'AGGRESSIVE' in long_tendency and 'PASSIVE' in short_tendency:
            insights.append("⚖️ **Asymmetric Behavior**: Long orders tend to be more aggressive while short orders are more passive")
        
        if comparison:
            oracle_diff = abs(comparison.get('oracle_deviation_diff_bps', 0))
            if oracle_diff > 10:
                bias = comparison.get('directional_bias', '')
                insights.append(f"🎯 **Significant Directional Bias**: {bias} orders consistently perform better (>{safe_format(oracle_diff, '.1f')} bps difference)")
    
    if insights:
        for insight in insights:
            st.markdown(insight)
    else:
        st.info("📈 Auction performance appears balanced between long and short directions")
