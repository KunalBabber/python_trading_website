from flask import Flask, render_template, request, Response, jsonify
import queue
import threading
import time
import json
from bot import TradingBot

app = Flask(__name__)

# Global variables
bot_thread = None
bot_instance = None
log_queue = queue.Queue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_bot():
    global bot_thread, bot_instance

    if bot_thread and bot_thread.is_alive():
        return jsonify({'status': 'error', 'message': 'Bot is already running!'})

    data = request.json
    
    try:
        bot_instance = TradingBot(
            api_key=data['api_key'],
            api_secret=data['api_secret'],
            base_url=data['base_url'],
            api_symbol=data['api_symbol'],
            ccxt_symbol=data['ccxt_symbol'],
            timeframe=data['timeframe'],
            order_size=data['order_size'],
            leverage=data['leverage'],
            log_queue=log_queue
        )
        
        bot_thread = threading.Thread(target=bot_instance.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        return jsonify({'status': 'success', 'message': 'Bot started successfully!'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop', methods=['POST'])
def stop_bot():
    global bot_instance
    if bot_instance:
        bot_instance.stop_event.set()
        return jsonify({'status': 'success', 'message': 'Bot stopping...'})
    return jsonify({'status': 'error', 'message': 'Bot not running'})

@app.route('/stream')
def stream_logs():
    def event_stream():
        while True:
            try:
                message = log_queue.get(timeout=1)
                yield f"data: {json.dumps(message)}\n\n"
            except queue.Empty:
                # Send a keep-alive comment to prevent connection timeout
                yield ": keep-alive\n\n"
    
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == '__main__':
    print("🚀 Flask App Initialized - Open http://127.0.0.1:5000 and click 'Start Bot' to see logs...", flush=True)
    app.run(debug=True, threaded=True)
