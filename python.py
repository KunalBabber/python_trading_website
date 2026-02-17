import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# === CONFIGURATION ===
api_symbol = 'BTCUSD'            # For Delta API
ccxt_symbol = 'BTC/USDT:USDT'    # For ccxt OHLCV data
timeframe = '15m'
order_size = 4
leverage_value = 10

delta_api_key = 'IpwDhHMmfpCWXhyhaTZXT8Z54wxzR0'
delta_api_secret = 'dAReMsaU8RR6zkrl7AenTyJlgisniLOKi3CrBGY5gTijucG3xePXAxk9A1k1'
delta_base_url = 'https://cdn-ind.testnet.deltaex.org'

# === Initialize CCXT Exchange ===
exchange = ccxt.delta({'enableRateLimit': True})


# === Signing Function ===
def sign_request(api_path, method, body):
    payload = json.dumps(body, separators=(',', ':'), sort_keys=True) if body else ""
    timestamp = str(int(time.time()))
    sign_str = method + timestamp + api_path + payload
    signature = hmac.new(delta_api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

    return {
        'api-key': delta_api_key,
        'timestamp': timestamp,
        'signature': signature,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'python-3.12'
    }


# === Fetch Product ID ===
def fetch_product_id(symbol):
    try:
        response = requests.get(delta_base_url + "/v2/products")
        data = response.json()
        for product in data["result"]:
            if product.get("symbol") == symbol:
                print(f"[✅] Found product ID: {product['id']} for {symbol}")
                return product["id"]
        print(f"[⚠️] Symbol {symbol} not found.")
        return None
    except Exception as e:
        print(f"[⚠️] Error fetching product ID: {str(e)}")
        return None


# === Set Leverage ===
def set_leverage(product_id, leverage):
    endpoint = f'/v2/products/{product_id}/leverage'
    payload = {"leverage": leverage}
    headers = sign_request(endpoint, "POST", payload)
    try:
        response = requests.post(delta_base_url + endpoint, headers=headers, data=json.dumps(payload))
        if response.status_code == 200 and response.json().get('success'):
            print(f"[⚙️] Leverage set to {leverage}x")
        else:
            print(f"[❌] Failed to set leverage: {response.text}")
    except Exception as e:
        print(f"[⚠️] Error setting leverage: {str(e)}")


# === Fetch Candle Data ===
def fetch_ohlcv():
    candles = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=100)
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


# === SUPERTREND STRATEGY ===
def calculate_supertrend(df, atr_period=10, factor=4):
    supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=atr_period, multiplier=factor)
    df = pd.concat([df, supertrend], axis=1)
    sup_col = f"SUPERT_{atr_period}_{factor}.0"
    dir_col = f"SUPERTd_{atr_period}_{factor}.0"
    df.rename(columns={sup_col: 'supertrend', dir_col: 'direction'}, inplace=True)
    return df



def generate_signal(df):
    df = calculate_supertrend(df)
    direction_prev = df['direction'].iloc[-2]
    direction_curr = df['direction'].iloc[-1]

    if direction_prev == 1 and direction_curr == -1:
        return "sell"
    elif direction_prev == -1 and direction_curr == 1:
        return "buy"
    else:
        return None


# === PLACE ORDER ===
def place_order(side, product_id):
    print(f"\n[🚀] {datetime.now()} Placing {side.upper()} order...")
    endpoint = '/v2/orders'
    order = {
        "product_id": product_id,
        "size": order_size,
        "side": side,
        "order_type": "market_order"
    }

    headers = sign_request(endpoint, "POST", order)
    payload = json.dumps(order, separators=(',', ':'), sort_keys=True)

    try:
        response = requests.post(delta_base_url + endpoint, headers=headers, data=payload)
        res = response.json()
        print("[🌐] Raw:", response.text)
        if response.status_code == 200 and res.get('success'):
            print(f"[✅] Order executed successfully: {res['result']}")
        else:
            print(f"[❌] Failed: {res.get('meta', {}).get('message', 'Unknown error')}")
    except Exception as e:
        print(f"[⚠️] Order error: {str(e)}")


# === MAIN LOOP ===
def main():
    print("\n🚦 Starting Supertrend Auto-Trader (Real-Time Mode)\n")

    product_id = fetch_product_id(api_symbol)
    if not product_id:
        print("[🛑] Cannot proceed without valid product ID.")
        return

    set_leverage(product_id, leverage_value)
    last_signal_time = None
    current_position = None

    while True:
        try:
            df = fetch_ohlcv()
            latest_timestamp = df['timestamp'].iloc[-1]
            signal = generate_signal(df)
            price = df['close'].iloc[-1]

            if last_signal_time != latest_timestamp:
                print(f"🕒 {datetime.now()} | Price: {price} | Signal: {signal or 'None'}")

                if signal:
                    if current_position is None:
                        print(f"🔔 Opening {signal.upper()} position")
                        place_order(signal, product_id)
                        current_position = signal
                    elif current_position != signal:
                        print(f"[🔁] Reversing position from {current_position.upper()} to {signal.upper()}")
                        reverse = 'buy' if current_position == 'sell' else 'sell'
                        place_order(reverse, product_id)
                        time.sleep(2)
                        place_order(signal, product_id)
                        current_position = signal
                    else:
                        print(f"[🔄] Already in {current_position.upper()} – No action")

                    last_signal_time = latest_timestamp
                else:
                    print(f"📉 No trend change – Holding {current_position or 'No position'}")
            else:
                print(f"⏳ Same candle – Waiting...")

        except Exception as e:
            print(f"[⚠️] Runtime Error: {str(e)}")

        time.sleep(5)  # Wait 1 minute between checks


if __name__ == "__main__":
    main()
import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# === CONFIGURATION ===
api_symbol = 'BTCUSD'            # For Delta API
ccxt_symbol = 'BTC/USDT:USDT'    # For ccxt OHLCV data
timeframe = '15m'
order_size = 4
leverage_value = 10

delta_api_key = 'IpwDhHMmfpCWXhyhaTZXT8Z54wxzR0'
delta_api_secret = 'dAReMsaU8RR6zkrl7AenTyJlgisniLOKi3CrBGY5gTijucG3xePXAxk9A1k1'
delta_base_url = 'https://cdn-ind.testnet.deltaex.org'

# === Initialize CCXT Exchange ===
exchange = ccxt.delta({'enableRateLimit': True})


# === Signing Function ===
def sign_request(api_path, method, body):
    payload = json.dumps(body, separators=(',', ':'), sort_keys=True) if body else ""
    timestamp = str(int(time.time()))
    sign_str = method + timestamp + api_path + payload
    signature = hmac.new(delta_api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

    return {
        'api-key': delta_api_key,
        'timestamp': timestamp,
        'signature': signature,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'python-3.12'
    }


# === Fetch Product ID ===
def fetch_product_id(symbol):
    try:
        response = requests.get(delta_base_url + "/v2/products")
        data = response.json()
        for product in data["result"]:
            if product.get("symbol") == symbol:
                print(f"[✅] Found product ID: {product['id']} for {symbol}")
                return product["id"]
        print(f"[⚠️] Symbol {symbol} not found.")
        return None
    except Exception as e:
        print(f"[⚠️] Error fetching product ID: {str(e)}")
        return None


# === Set Leverage ===
def set_leverage(product_id, leverage):
    endpoint = f'/v2/products/{product_id}/leverage'
    payload = {"leverage": leverage}
    headers = sign_request(endpoint, "POST", payload)
    try:
        response = requests.post(delta_base_url + endpoint, headers=headers, data=json.dumps(payload))
        if response.status_code == 200 and response.json().get('success'):
            print(f"[⚙️] Leverage set to {leverage}x")
        else:
            print(f"[❌] Failed to set leverage: {response.text}")
    except Exception as e:
        print(f"[⚠️] Error setting leverage: {str(e)}")


# === Fetch Candle Data ===
def fetch_ohlcv():
    candles = exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=100)
    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


# === SUPERTREND STRATEGY ===
def calculate_supertrend(df, atr_period=10, factor=4):
    supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=atr_period, multiplier=factor)
    df = pd.concat([df, supertrend], axis=1)
    sup_col = f"SUPERT_{atr_period}_{factor}.0"
    dir_col = f"SUPERTd_{atr_period}_{factor}.0"
    df.rename(columns={sup_col: 'supertrend', dir_col: 'direction'}, inplace=True)
    return df



def generate_signal(df):
    df = calculate_supertrend(df)
    direction_prev = df['direction'].iloc[-2]
    direction_curr = df['direction'].iloc[-1]

    if direction_prev == 1 and direction_curr == -1:
        return "sell"
    elif direction_prev == -1 and direction_curr == 1:
        return "buy"
    else:
        return None


# === PLACE ORDER ===
def place_order(side, product_id):
    print(f"\n[🚀] {datetime.now()} Placing {side.upper()} order...")
    endpoint = '/v2/orders'
    order = {
        "product_id": product_id,
        "size": order_size,
        "side": side,
        "order_type": "market_order"
    }

    headers = sign_request(endpoint, "POST", order)
    payload = json.dumps(order, separators=(',', ':'), sort_keys=True)

    try:
        response = requests.post(delta_base_url + endpoint, headers=headers, data=payload)
        res = response.json()
        print("[🌐] Raw:", response.text)
        if response.status_code == 200 and res.get('success'):
            print(f"[✅] Order executed successfully: {res['result']}")
        else:
            print(f"[❌] Failed: {res.get('meta', {}).get('message', 'Unknown error')}")
    except Exception as e:
        print(f"[⚠️] Order error: {str(e)}")


# === MAIN LOOP ===
def main():
    print("\n🚦 Starting Supertrend Auto-Trader (Real-Time Mode)\n")

    product_id = fetch_product_id(api_symbol)
    if not product_id:
        print("[🛑] Cannot proceed without valid product ID.")
        return

    set_leverage(product_id, leverage_value)
    last_signal_time = None
    current_position = None

    while True:
        try:
            df = fetch_ohlcv()
            latest_timestamp = df['timestamp'].iloc[-1]
            signal = generate_signal(df)
            price = df['close'].iloc[-1]

            if last_signal_time != latest_timestamp:
                print(f"🕒 {datetime.now()} | Price: {price} | Signal: {signal or 'None'}")

                if signal:
                    if current_position is None:
                        print(f"🔔 Opening {signal.upper()} position")
                        place_order(signal, product_id)
                        current_position = signal
                    elif current_position != signal:
                        print(f"[🔁] Reversing position from {current_position.upper()} to {signal.upper()}")
                        reverse = 'buy' if current_position == 'sell' else 'sell'
                        place_order(reverse, product_id)
                        time.sleep(2)
                        place_order(signal, product_id)
                        current_position = signal
                    else:
                        print(f"[🔄] Already in {current_position.upper()} – No action")

                    last_signal_time = latest_timestamp
                else:
                    print(f"📉 No trend change – Holding {current_position or 'No position'}")
            else:
                print(f"⏳ Same candle – Waiting...")

        except Exception as e:
            print(f"[⚠️] Runtime Error: {str(e)}")

        time.sleep(5)  # Wait 1 minute between checks


if __name__ == "__main__":
    main()
