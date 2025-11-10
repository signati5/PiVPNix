# web/service_manager.py

import os
import re
import subprocess
from flask import Blueprint, render_template, current_app, request, jsonify

from .auth import login_required

service_bp = Blueprint('service_manager', __name__)

def _get_wireguard_interfaces():
    """
    Scans the WireGuard configuration directory to find all
    possible interface configuration files (e.g., wg0.conf, wg1.conf).
    """
    wg_server_path = current_app.config['WG_SERVER_CONFIG_PATH']
    interfaces = []
    try:
        if os.path.isdir(wg_server_path):
            for filename in sorted(os.listdir(wg_server_path)):
                full_path = os.path.join(wg_server_path, filename)
                if filename.endswith('.conf') and os.path.isfile(full_path):
                    # Append the filename without the .conf extension
                    interfaces.append(os.path.splitext(filename)[0])
    except FileNotFoundError:
        current_app.logger.warning(f"WireGuard server directory '{wg_server_path}' not found.")
    return interfaces

def _parse_systemctl_status(output):
    """
    Extracts essential information from the 'systemctl status' output.
    Focuses on parsing the active/inactive/failed state.
    """
    data = {'raw': output, 'active': 'unknown', 'status_text': 'N/A'}
    
    # Search for the "Active:" line in the multi-line output
    active_match = re.search(r'^\s*Active:\s*(.+)', output, re.MULTILINE)
    if active_match:
        status_line = active_match.group(1).strip()
        data['status_text'] = status_line # E.g., "active (running) since ..."
        
        # More specific and robust checks for the service state
        if status_line.startswith('active'):
            data['active'] = 'active'
        elif status_line.startswith('inactive'):
            data['active'] = 'inactive'
        elif status_line.startswith('failed'):
            data['active'] = 'failed'
            
    return data

def _parse_wg_show(output):
    """Extracts key information from the 'wg show' output."""
    data = {'raw': output, 'public_key': None, 'port': None}
    # If the interface is down, the output will be empty
    if not output.strip():
        return data

    key_match = re.search(r'^\s*public key:\s*(.+)', output, re.MULTILINE)
    if key_match:
        data['public_key'] = key_match.group(1)
        
    port_match = re.search(r'^\s*listening port:\s*(.+)', output, re.MULTILINE)
    if port_match:
        data['port'] = port_match.group(1)
        
    return data

@service_bp.route('/')
@login_required
def manager():
    """Renders the main service manager page."""
    interfaces = _get_wireguard_interfaces()
    return render_template('service_manager.html', interfaces=interfaces)


# --- API Endpoints ---

@service_bp.route('/api/status')
@login_required
def get_status():
    """Returns the combined status of a WireGuard interface and its systemd service."""
    interface = request.args.get('interface')
    if not interface or not re.match(r'^[a-zA-Z0-9_-]+$', interface):
        return jsonify({"error": "Invalid interface name."}), 400

    # 1. Get systemd service status
    try:
        service_name = f"wg-quick@{interface}.service"
        # Using 'sudo' here. 'check=False' is CRUCIAL because 'systemctl status'
        # returns a non-zero exit code (3) for inactive services, which
        # would otherwise raise an exception.
        result = subprocess.run(
            ['sudo', 'systemctl', 'status', service_name],
            capture_output=True, text=True, check=False 
        )
        # Even if there's an error (e.g., service not found), we process the output.
        systemctl_data = _parse_systemctl_status(result.stdout or result.stderr)
    except Exception as e:
        # This catches more severe errors, like sudo or permission issues.
        current_app.logger.error(f"Error executing systemctl for {interface}: {e}")
        systemctl_data = {'active': 'error', 'status_text': str(e)}

    # 2. Get WireGuard interface status
    try:
        result = subprocess.run(
            ['sudo', 'wg', 'show', interface],
            capture_output=True, text=True, check=False
        )
        # If the interface is down, 'wg show' produces no output and has exit code 0.
        # If the interface does not exist, it has a non-zero exit code.
        # We parse the output only if the command was successful.
        wg_data = _parse_wg_show(result.stdout if result.returncode == 0 else "")
    except Exception as e:
        wg_data = {'public_key': 'Error', 'port': str(e)}

    return jsonify({
        "interface": interface,
        "service": systemctl_data,
        "wireguard": wg_data
    })


@service_bp.route('/api/action', methods=['POST'])
@login_required
def service_action():
    """Starts or stops a WireGuard service."""
    data = request.get_json()
    interface = data.get('interface')
    action = data.get('action')

    if not interface or not re.match(r'^[a-zA-Z0-9_-]+$', interface):
        return jsonify({"error": "Invalid interface name."}), 400
    if action not in ['start', 'stop']:
        return jsonify({"error": "Invalid action."}), 400

    try:
        service_name = f"wg-quick@{interface}.service"
        # Use sudo for action commands (start/stop)
        result = subprocess.run(
            ['sudo', 'systemctl', action, service_name],
            capture_output=True, text=True, check=True # check=True will raise an exception on failure
        )
        # The f-string trick "start" + "ed" -> "started", "stop" + "ped" -> "stopped"
        # Let's make it more robust.
        past_tense_action = "started" if action == "start" else "stopped"
        return jsonify({"message": f"Service '{interface}' {past_tense_action} successfully."})
    except subprocess.CalledProcessError as e:
        error_message = e.stderr or e.stdout
        current_app.logger.error(f"Error during '{action}' for '{interface}': {error_message}")
        return jsonify({"error": f"Failed: {error_message}"}), 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error during '{action}' for '{interface}': {e}")
        return jsonify({"error": "An unexpected server error occurred."}), 500