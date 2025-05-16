import streamlit as st
from solders.rpc.responses import GetSignaturesForAddressResp, GetTokenAccountBalanceResp, GetTransactionResp
import json
from anchorpy.provider import Signature, Provider
from solders.pubkey import Pubkey
import asyncio
from streamlit import cache_data
import os
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature

async def load_token_balance(connection, address):
    res: GetTokenAccountBalanceResp = (await connection.get_token_account_balance(address)).to_json()
    res2 = json.loads(res)
    v_amount = int(res2['result']['value']['amount'])
    return v_amount


async def transaction_history_for_account(connection, addy, before_sig1, limit, MAX_LIMIT):

    if isinstance(addy, str):
         addy = Pubkey.from_string(addy)

    res2 = []
    first_try = True
    while (first_try and len(res2) % 1000 == 0) and len(res2)< MAX_LIMIT:
        # try:
            if len(res2):
                bbs = res2[-1]['signature']
                bbs = Signature.from_string(bbs)
            else:
                bbs = before_sig1
            res: GetSignaturesForAddressResp = (await connection.get_signatures_for_address(addy, 
                                                                                            before=bbs, 
                                                                                            limit=limit
                                                                                            )).to_json()
            res = json.loads(res)
            if 'result' not in res:
                st.warning('bad get_signatures_for_address' + str(res))
                first_try = False
            else:
                res2.extend(res['result'])
        # except Exception as e:
        #     st.warning('exception:'+str(e))
        #     first_try = False

    return res2

async def get_slot_for_tx(tx_signature: str, connection=None):
    """
    Fetches the slot number for a given transaction signature using solders/anchorpy.
    
    Args:
        tx_signature: The transaction signature (hash) as a string
        connection: Optional RPC connection to use (will create one if not provided)
        
    Returns:
        The slot number as an integer, or None if the transaction is not found
    """
    try:
        # Use provided connection or create a new one
        if connection is None:
            # Get RPC URL from environment variable or use default
            rpc_url = os.environ.get("ANCHOR_PROVIDER_URL", "https://api.mainnet-beta.solana.com")
            
            # Create a connection using the RPC URL
            connection = AsyncClient(rpc_url)
        
        # Convert string signature to Signature object
        signature = Signature.from_string(tx_signature)
        
        # Fetch the transaction
        tx_response = await connection.get_transaction(
            signature,
            max_supported_transaction_version=0
        )
        
        # Check if transaction was found
        if tx_response is None:
            print(f"Transaction not found: {tx_signature}")
            return None
            
        # The response structure depends on the client implementation
        # Try to handle both dictionary and object responses
        if hasattr(tx_response, 'value') and tx_response.value:
            # It's a GetTransactionResp object
            return tx_response.value.slot
        elif isinstance(tx_response, dict) and 'result' in tx_response:
            # It's a dictionary with a result key
            return tx_response['result']['slot']
        else:
            print(f"Unexpected response format for transaction {tx_signature}")
            print(tx_response)
            return None
        
    except Exception as e:
        print(f"Error fetching slot for transaction {tx_signature}: {str(e)}")
        return None