import os
import sys
import socket
import threading
import time
import json
import webview

# Add parent directory to sys.path so we can import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app

def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def run_flask(port):
    # Run the Flask app on localhost only.
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

def main():
    # Setup a default sync_config.json if it does not exist
    os.makedirs(app.instance_path, exist_ok=True)
    config_path = os.path.join(app.instance_path, "sync_config.json")
    if not os.path.exists(config_path):
        default_config = {
            "remote_sync_url": "http://localhost:5001"  # Default remote sync URL
        }
        try:
            with open(config_path, "w") as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            print(f"Error writing default sync config: {e}")

    port = find_free_port()
    
    # Start Flask in a background thread
    t = threading.Thread(target=run_flask, args=(port,), daemon=True)
    t.start()
    
    # Wait for the flask server to start
    time.sleep(1.0)
    
    url = f"http://127.0.0.1:{port}"
    print(f"Launching pywebview pointing to {url}")
    
    # Create webview window
    webview.create_window("N890GF Tracker", url, width=1280, height=800)
    
    # Start the webview loop
    webview.start()
    
    # Exit process when window closes
    sys.exit(0)

if __name__ == '__main__':
    main()
