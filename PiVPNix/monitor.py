# monitor.py

import subprocess
import json
import os
import shutil
import time
import threading
from datetime import datetime
from flask import current_app

# --- Global variables for thread management ---
# Holds the single global instance of the monitor thread.
_monitor_thread = None
# A lock to ensure that checking and starting the thread is an atomic operation,
# preventing race conditions where two calls to start_monitor could create two threads.
_thread_lock = threading.Lock()


def run_monitoring_cycle(skip_updates=False):
    """
    Executes a single monitoring cycle and updates the JSON log file.
    It retrieves all necessary configuration from 'current_app.config'.
    
    :param skip_updates: If True, the byte history and 'last_update' timestamp will not be updated.
                         This is useful for manual refreshes that shouldn't affect time-series data.
    """
    try:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [MONITOR] Running WireGuard traffic check...")
        if skip_updates:
            print("[MONITOR] 'skip_updates' mode is active.")

        # --- Execute the pivpn command to get client status ---
        result = subprocess.run(
            ["pivpn", "-c", "-b"], capture_output=True, text=True, check=True, encoding='utf-8'
        )
        
        # --- Parse the command output ---
        parsed_clients = []
        lines = result.stdout.strip().split('\n')
        parsing_mode = None
        for line in lines:
            if "::: Connected Clients List :::" in line: parsing_mode = 'connected'; continue
            if "::: Disabled clients :::" in line: parsing_mode = 'disabled'; continue
            if not line or "Name" in line or "----" in line: continue # Skip headers and empty lines
            
            cleaned_line = line.strip()
            if cleaned_line.startswith('[disabled]'):
                client_name = cleaned_line.replace('[disabled]', '').strip().split()[0]
                parsed_clients.append({'name': client_name, 'status': 'disabled'})
                continue
            
            if parsing_mode == 'connected':
                parts = cleaned_line.split(None, 5)
                if len(parts) != 6: continue
                name, remote_ip_str, virtual_ip, bytes_rx, bytes_tx, last_seen_str = parts
                
                remote_ip, remote_port = (None, None)
                if ':' in remote_ip_str and remote_ip_str != '(none)':
                    remote_ip, port_str = remote_ip_str.rsplit(':', 1)
                    remote_port = int(port_str) if port_str.isdigit() else None
                
                parsed_last_seen = None
                if last_seen_str.strip() != '(not yet)':
                    try:
                        dt_object = datetime.strptime(last_seen_str.strip(), '%b %d %Y - %H:%M:%S')
                        parsed_last_seen = dt_object.isoformat()
                    except ValueError: 
                        parsed_last_seen = last_seen_str.strip()
                
                parsed_clients.append({
                    'name': name, 'status': 'pending', 'virtual_ip': virtual_ip, 'remote_ip': remote_ip,
                    'remote_port': remote_port, 'total_bytes_received': int(bytes_rx),
                    'total_bytes_sent': int(bytes_tx), 'last_seen': parsed_last_seen
                })

        # --- Load existing data and process the newly parsed data ---
        existing_data = {"hosts": [], "max_scale": 0, "update_timestamps": []}
        log_file_path = current_app.config['LOG_FILE']
        if os.path.exists(log_file_path):
            try:
                with open(log_file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except json.JSONDecodeError:
                print(f"[MONITOR] Warning: file '{log_file_path}' is corrupted and will be overwritten.")
        
        current_max_scale = 50 # A small default value to prevent an empty graph
        host_map = {host['name']: host for host in existing_data.get('hosts', [])}
        
        updated_clients = []
        for client in parsed_clients:
            if client['status'] == 'disabled':
                updated_clients.append(client)
                continue

            previous_host_data = host_map.get(client['name'])
            
            if not skip_updates:
                if previous_host_data:
                    # Calculate traffic delta since the last check
                    delta_rx = max(0, client['total_bytes_received'] - previous_host_data.get('total_bytes_received', 0))
                    delta_tx = max(0, client['total_bytes_sent'] - previous_host_data.get('total_bytes_sent', 0))
                    bytes_rx_hist = previous_host_data.get('bytes_received', []) + [delta_rx]
                    bytes_tx_hist = previous_host_data.get('bytes_sent', []) + [delta_tx]
                    # Keep only the N most recent history entries
                    client['bytes_received'] = bytes_rx_hist[-current_app.config['HISTORY_SIZE']:]
                    client['bytes_sent'] = bytes_tx_hist[-current_app.config['HISTORY_SIZE']:]
                else:
                    # This is a new client, start its history with zero
                    client['bytes_received'], client['bytes_sent'] = [0], [0]
            else:
                # If skipping updates, just carry over the old history
                client['bytes_received'] = previous_host_data.get('bytes_received', []) if previous_host_data else []
                client['bytes_sent'] = previous_host_data.get('bytes_sent', []) if previous_host_data else []

            traffic_history_rx = client.get('bytes_received', [])
            traffic_history_tx = client.get('bytes_sent', [])
            current_max_scale = max(current_max_scale, max(traffic_history_rx, default=0), max(traffic_history_tx, default=0))
            
            # --- Status determination logic ---
            # Offline: No traffic ever, or no traffic for the last N intervals.
            if (client['total_bytes_received'] == 0) or \
               (len(traffic_history_rx) >= current_app.config['NOT_CONN_FOR_SIZE'] and all(v == 0 for v in traffic_history_rx[-current_app.config['NOT_CONN_FOR_SIZE']:])):
                client['status'] = 'offline'
            # Idle: No traffic for the entire history length.
            elif len(traffic_history_rx) >= current_app.config['HISTORY_SIZE'] and all(v == 0 for v in traffic_history_rx[-current_app.config['HISTORY_SIZE']:]):
                client['status'] = 'idle'
            # Online: Traffic was received in the very last interval.
            elif traffic_history_rx and traffic_history_rx[-1] > 0:
                client['status'] = 'online'
            # Caching: No traffic in the last interval, but there was traffic recently.
            else:
                client['status'] = 'caching'
                
            updated_clients.append(client)

        # --- Write the updated data to the log file ---
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        timestamp_history = existing_data.get('update_timestamps', [])
        updated_data = {"max_scale": current_max_scale, "hosts": updated_clients}

        if not skip_updates:
            current_timestamp = int(time.time())
            updated_data["last_update"] = current_timestamp
            timestamp_history.append(current_timestamp)
            updated_data["update_timestamps"] = timestamp_history[-current_app.config['HISTORY_SIZE']:]
        else:
            updated_data["last_update"] = existing_data.get('last_update')
            updated_data["update_timestamps"] = timestamp_history
        
        # Define the path for the temporary file
        temp_file_path = log_file_path + ".tmp"

        try:
            # 1. Write the new data to the temporary file
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(updated_data, f, indent=4)
            
            # 2. If writing succeeds, atomically rename the temporary file
            #    to replace the original one. On POSIX systems, os.rename is atomic.
            #    We use shutil.move for better portability (e.g., Windows).
            shutil.move(temp_file_path, log_file_path)
            
            print(f"[MONITOR] Log file '{log_file_path}' has been updated atomically.")

        except Exception as e:
            # If something goes wrong, make sure to remove the temporary file
            print(f"[MONITOR] Error during atomic write: {e}. The original log file was not modified.")
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            # Re-raise the exception so it can be handled by an outer try/except block
            raise
    
    except subprocess.CalledProcessError as e:
        print(f"[MONITOR] Error running pivpn command (exit code {e.returncode}): {e.stderr.strip()}")
    except Exception as e:
        print(f"[MONITOR] Error during monitoring cycle: {e}")


def _monitor_worker_loop(app):
    """
    The main worker function that runs the infinite monitoring loop.
    This function is designed to be run in a separate thread. It uses the
    application context to make 'current_app' available.
    
    :param app: The Flask application instance.
    """
    print("[MONITOR] Monitoring worker started.")
    
    # This 'with' is essential: it creates a context where the thread
    # can access 'current_app' as if it were a web request.
    with app.app_context():
        interval = current_app.config.get('UPDATE_INTERVAL', 30)
        log_file_path = current_app.config['LOG_FILE']

        # On startup, check if the last update was too recent to avoid hammering the system.
        if os.path.isfile(log_file_path) and os.path.getsize(log_file_path) > 50:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                last_update_time = json.load(f).get("last_update", 0)
                elapsed = time.time() - last_update_time
                if elapsed < interval:
                    to_wait = interval - elapsed
                    print(f"Last update was {elapsed:.2f}s ago (less than the {interval}s interval). Waiting for {to_wait:.2f}s.")
                    time.sleep(to_wait)
        else:
            print("Log file is missing or empty, skipping initial wait.")

        while True:
            try:
                run_monitoring_cycle()
                time.sleep(interval)
            except Exception as e:
                print(f"[MONITOR] Critical error in worker loop: {e}. Retrying in 60 seconds...")
                time.sleep(60)

def start_monitor(app):
    """
    Starts the background monitoring thread if it's not already running.
    This function is thread-safe and can be called multiple times without creating duplicate threads.
    
    :param app: The Flask application instance.
    """
    global _monitor_thread
    
    # The lock ensures this block of code cannot be executed by two threads simultaneously,
    # preventing the creation of multiple monitor threads.
    with _thread_lock:
        # Check if the thread object exists and if it is currently running.
        if _monitor_thread and _monitor_thread.is_alive():
            print("[MONITOR] Attempted to start, but the monitor thread is already running.")
            return

        # If the thread doesn't exist or has terminated, create a new one.
        print("[MONITOR] Starting the background monitor thread...")
        
        # daemon=True ensures that this thread will exit when the main application process terminates.
        _monitor_thread = threading.Thread(target=_monitor_worker_loop, args=(app,), daemon=True)
        _monitor_thread.start()
