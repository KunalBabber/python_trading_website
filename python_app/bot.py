import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests
import hmac
import hashlib
import json
from datetime import datetime
import threading
import queue

class TradingBot:
    def __init__(self, api_key, api_secret, base_url, api_symbol, ccxt_symbol, timeframe, order_size, leverage, log_queue):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.api_symbol = api_symbol
        self.ccxt_symbol = ccxt_symbol.upper() # Ensure uppercase for CCXT
        self.timeframe = timeframe
        self.order_size = float(order_size)
        self.leverage = int(leverage)
        self.log_queue = log_queue
        
        self.stop_event = threading.Event()
        
        # Configure CCXT with default mainnet, as per user script
        self.exchange = ccxt.delta({'enableRateLimit': True})

        
        self.product_id = None
        self.current_position = None
        self.last_signal_time = None

    def log(self, message, type="INFO"):
        """Sends a log message to the queue for the UI."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "time": timestamp,
            "type": type,
            "message": message
        }
        self.log_queue.put(log_entry)
        print(f"[{timestamp}] [{type}] {message}", flush=True) # Keep console for debugging

    def sign_request(self, api_path, method, body):
        payload = json.dumps(body, separators=(',', ':'), sort_keys=True) if body else ""
        timestamp = str(int(time.time()))
        sign_str = method + timestamp + api_path + payload
        signature = hmac.new(self.api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

        return {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'python-3.12'
        }

    def fetch_product_id(self):
        try:
            response = requests.get(self.base_url + "/v2/products")
            data = response.json()
            for product in data.get("result", []):
                if product.get("symbol") == self.api_symbol:
                    self.log(f"✅ Found product ID: {product['id']} for {self.api_symbol}", "SUCCESS")
                    return product["id"]
            self.log(f"⚠️ Symbol {self.api_symbol} not found.", "ERROR")
            return None
        except Exception as e:
            self.log(f"⚠️ Error fetching product ID: {str(e)}", "ERROR")
            return None

    def set_leverage(self):
        if not self.product_id: return
        endpoint = f'/v2/products/{self.product_id}/leverage'
        payload = {"leverage": self.leverage}
        headers = self.sign_request(endpoint, "POST", payload)
        try:
            response = requests.post(self.base_url + endpoint, headers=headers, data=json.dumps(payload))
            if response.status_code == 200 and response.json().get('success'):
                self.log(f"⚙️ Leverage set to {self.leverage}x", "SUCCESS")
            else:
                self.log(f"❌ Failed to set leverage: {response.text}", "ERROR")
        except Exception as e:
            self.log(f"⚠️ Error setting leverage: {str(e)}", "ERROR")

    def fetch_ohlcv(self):
        try:
            # Fetch 100 candles as per user script (was 300)
            candles = self.exchange.fetch_ohlcv(self.ccxt_symbol, self.timeframe, limit=100)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.log(f"Error fetching candles: {str(e)}", "ERROR")
            return pd.DataFrame()

    def calculate_supertrend(self, df, atr_period=10, factor=1.6):
        try:
            supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=atr_period, multiplier=factor)
            if supertrend is None or supertrend.empty:
                self.log("Supertrend calculation returned empty/None", "ERROR")
                return df
            
            # self.log(f"Supertrend Columns: {list(supertrend.columns)}", "INFO") # Debug
            
            # pandas_ta returns columns like SUPERT_10_4.0, SUPERTd_10_4.0, SUPERTl_10_4.0, SUPERTs_10_4.0
            # We need to find the value column and the direction column dynamically
            
            sup_col = cls_col = dir_col = None
            
            for col in supertrend.columns:
                if col.startswith(f"SUPERT_{atr_period}_{factor}"):
                    sup_col = col
                elif col.startswith(f"SUPERTd_{atr_period}_{factor}"):
                    dir_col = col
            
            if not sup_col or not dir_col:
                self.log(f"Could not find likely Supertrend columns in {list(supertrend.columns)}", "ERROR")
                return df

            df = pd.concat([df, supertrend], axis=1)
            df.rename(columns={sup_col: 'supertrend', dir_col: 'direction'}, inplace=True)
            return df
        except Exception as e:
            self.log(f"Error in supertrend calc: {e}", "ERROR")
            return df

    def generate_signal(self, df):
        if df.empty: return None
        # df = self.calculate_supertrend(df) # Moved to main loop
        
        if 'direction' not in df.columns:
            # self.log("Column 'direction' missing from DataFrame", "ERROR") # Redundant if checked in main
            return None
            
        direction_prev = df['direction'].iloc[-2]
        direction_curr = df['direction'].iloc[-1]


        if direction_prev == 1 and direction_curr == -1:
            return "sell"
        elif direction_prev == -1 and direction_curr == 1:
            return "buy"
        else:
            return None

    def place_order(self, side):
        self.log(f"🚀 Placing {side.upper()} order...", "INFO")
        endpoint = '/v2/orders'
        order = {
            "product_id": self.product_id,
            "size": self.order_size,
            "side": side,
            "order_type": "market_order"
        }

        headers = self.sign_request(endpoint, "POST", order)
        payload = json.dumps(order, separators=(',', ':'), sort_keys=True)

        try:
            response = requests.post(self.base_url + endpoint, headers=headers, data=payload)
            self.log(f"🌐 Raw: {response.text}", "INFO") # Matched user script
            
            res = response.json()
            if response.status_code == 200 and res.get('success'):
                self.log(f"✅ Order executed successfully: {res.get('result', 'Success')}", "SUCCESS")
            else:
                error_msg = res.get('error', {}).get('message') or res.get('meta', {}).get('message', 'Unknown error')
                self.log(f"❌ Failed: {error_msg}", "ERROR")
        except Exception as e:
            self.log(f"⚠️ Order error: {str(e)}", "ERROR")

    def run(self):
        self.log("🚦 Starting Supertrend Auto-Trader (Real-Time Mode)", "INFO")
        self.product_id = self.fetch_product_id()
        if not self.product_id:
            self.log("🛑 Cannot proceed without valid product ID.", "ERROR")
            return

        self.set_leverage()

        while not self.stop_event.is_set():
            try:
                df = self.fetch_ohlcv()
                if not df.empty:
                    # Calculate indicators HERE so df has them for logging
                    df = self.calculate_supertrend(df)
                    
                    if 'direction' in df.columns:
                        latest_timestamp = df['timestamp'].iloc[-1]
                        signal = self.generate_signal(df)
                        price = df['close'].iloc[-1]

                        if self.last_signal_time != latest_timestamp:
                            self.log(f"🕒 Price: {price} | Signal: {signal or 'None'}", "INFO")

                            if signal:
                                if self.current_position is None:
                                    self.log(f"🔔 Opening {signal.upper()} position", "INFO")
                                    self.place_order(signal)
                                    self.current_position = signal
                                elif self.current_position != signal:
                                    self.log(f"🔁 Reversing position from {self.current_position.upper()} to {signal.upper()}", "INFO")
                                    reverse_side = 'buy' if self.current_position == 'sell' else 'sell'
                                    self.place_order(reverse_side) # Close
                                    time.sleep(2)
                                    self.place_order(signal) # Open
                                    self.current_position = signal
                                else:
                                    self.log(f"🔄 Already in {self.current_position.upper()} – No action", "INFO")

                                self.last_signal_time = latest_timestamp
                            else:
                                self.log(f"📉 No trend change – Holding {self.current_position or 'No position'}", "INFO")
                        else:
                            self.log(f"⏳ Same candle – Waiting...", "INFO")
                    else:
                        self.log("⚠️ Failed to calculate Supertrend (missing direction)", "ERROR")

            except Exception as e:
                self.log(f"Runtime Error: {str(e)}", "ERROR")

            time.sleep(10)  # Loop delay increased to 10s due to API instability



        
        self.log("Bot Loop Stopped.", "INFO")

