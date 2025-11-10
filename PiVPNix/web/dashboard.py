# web/dashboard.py

import json
import os
import math
from datetime import datetime
from flask import Blueprint, render_template, current_app, jsonify

# Import our custom decorator
from web.auth import login_required

# Create the Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

def format_bytes(b, d=2):
    """
    Converts a number of bytes into a human-readable string with appropriate units.
    """
    # Handle non-numeric or negative inputs
    if not isinstance(b, (int, float)) or b < 0: return "N/A"
    # Handle the zero case
    if b == 0: return "0 Bytes"
    
    k = 1024
    sizes = ["Bytes", "KB", "MB", "GB", "TB"]
    # Calculate the index 'i' to determine the appropriate size unit (Bytes, KB, MB, etc.)
    i = min(int(math.floor(math.log(b) / math.log(k))), len(sizes) - 1)
    value = b / math.pow(k, i)
    return f"{value:.{d}f} {sizes[i]}"

def _calculate_kpi_data():
    """
    Reads the monitor log file and calculates a dictionary of Key Performance Indicators (KPIs).
    This is the core logic for the dashboard data.
    """
    # Initialize a dictionary with default KPI values.
    # This ensures the function always returns a consistently structured object, even if an error occurs.
    kpi_data = {
        "total_clients": 0, "online_clients": 0, "enabled_clients": 0, "disabled_clients": 0,
        "total_traffic": "0 Bytes", "last_update": 0, "top_clients": [], "recent_clients": [],
        "status_counts": {"online": 0, "caching": 0, "idle": 0, "offline": 0, "disabled": 0},
        "aggregate_traffic_received": 0,
        "aggregate_traffic_sent": 0,
        "timeseries_received": [],
        "timeseries_sent": [],
        "timeseries_labels": [] # This will be populated with the actual timestamps
    }
    try:
        log_file = current_app.config['LOG_FILE']
        # If the log file doesn't exist, return the default data immediately.
        if not os.path.exists(log_file):
            return kpi_data
        
        with open(log_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        all_clients = data.get('hosts', [])
        if not all_clients:
            return kpi_data

        # --- KEY CHANGE HERE ---
        # Instead of generating relative labels, we now retrieve the actual timestamps from the JSON file.
        # If the key doesn't exist, we default to an empty list to prevent errors.
        kpi_data["timeseries_labels"] = data.get('update_timestamps', [])
        
        # The rest of the function remains almost identical, but now uses more precise data.
        num_intervals = len(all_clients[0].get('bytes_received', [])) if all_clients else 0
        kpi_data["timeseries_received"] = [0] * num_intervals
        kpi_data["timeseries_sent"] = [0] * num_intervals
        
        clients_with_traffic, online_clients_list = [], []

        # Iterate over each client ('host') to aggregate statistics.
        for host in all_clients:
            # Update status counts and lists based on the client's current status.
            status = host.get('status', 'offline')
            if status in kpi_data["status_counts"]: kpi_data["status_counts"][status] += 1
            if status == 'online': kpi_data['online_clients'] += 1; online_clients_list.append(host)
            
            if status != 'disabled': kpi_data['enabled_clients'] += 1
            else: kpi_data['disabled_clients'] += 1
            
            # Aggregate total and time-series traffic data.
            total_received = host.get('total_bytes_received', 0)
            total_sent = host.get('total_bytes_sent', 0)
            
            kpi_data["aggregate_traffic_received"] += total_received
            kpi_data["aggregate_traffic_sent"] += total_sent

            for i, bytes_val in enumerate(host.get('bytes_received', [])):
                if i < num_intervals: kpi_data["timeseries_received"][i] += bytes_val
            for i, bytes_val in enumerate(host.get('bytes_sent', [])):
                if i < num_intervals: kpi_data["timeseries_sent"][i] += bytes_val

            # Store clients with their total traffic for later sorting.
            total_client_traffic = total_received + total_sent
            if total_client_traffic > 0:
                 clients_with_traffic.append({ 
                     "name": host['name'], 
                     "total_traffic": total_client_traffic, 
                     "total_traffic_formatted": format_bytes(total_client_traffic) 
                 })

        # Finalize KPI calculations after the loop.
        kpi_data['total_clients'] = len(all_clients)
        kpi_data['total_traffic'] = format_bytes(kpi_data["aggregate_traffic_received"] + kpi_data["aggregate_traffic_sent"])
        # Sort clients by total traffic to find the top 5.
        kpi_data['top_clients'] = sorted(clients_with_traffic, key=lambda x: x['total_traffic'], reverse=True)[:5]
        # Sort online clients by their last seen timestamp to find the 5 most recent.
        kpi_data['recent_clients'] = sorted(online_clients_list, key=lambda x: x.get('last_seen_timestamp', 0), reverse=True)[:5]
        kpi_data['last_update'] = data.get('last_update', 0)

    except Exception as e:
        current_app.logger.error(f"Error while calculating KPIs: {e}", exc_info=True)
    
    return kpi_data

@dashboard_bp.route('/')
@login_required
def dashboard():
    """Renders the dashboard with the calculated KPI data."""
    kpi_data = _calculate_kpi_data()
    return render_template('dashboard.html', kpi_data=kpi_data, update_interval=current_app.config.get('UPDATE_INTERVAL'))

@dashboard_bp.route('/api/kpi')
@login_required
def api_kpi():
    """API endpoint that returns the calculated KPI data in JSON format."""
    kpi_data = _calculate_kpi_data()
    return jsonify(kpi_data)