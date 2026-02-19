
import os
from web3 import Web3
from web3.middleware import geth_poa_middleware

# Use the RPCs we just configured
BSC_RPC_LIST = [
    'https://data-seed-prebsc-1-s1.binance.org:8545/',
    'https://data-seed-prebsc-2-s1.binance.org:8545/',
    'https://data-seed-prebsc-1-s2.binance.org:8545/',
    'https://bsc-testnet.publicnode.com'
]

def check_gas():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    for rpc in BSC_RPC_LIST:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={'verify': False}))
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            if w3.is_connected():
                gas_price_wei = w3.eth.gas_price
                gas_price_gwei = w3.from_wei(gas_price_wei, 'gwei')
                
                # Standard transfer gas limit
                gas_limit = 21000 
                fee_bnb = w3.from_wei(gas_price_wei * gas_limit, 'ether')
                
                print(f"Connected to: {rpc}")
                print(f"Current Gas Price: {gas_price_gwei} Gwei")
                print(f"Estimated Fee for Transfer (21000 gas): {fee_bnb} BNB")
                return
        except Exception as e:
            print(f"Failed {rpc}: {e}")

check_gas()
