# web/clients.py

import json
import os
import re
import subprocess
import io
import ipaddress
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, current_app, render_template

# Import our custom decorator
from web.auth import login_required
import monitor

# Create the Blueprint for the clients and its APIs
clients_bp = Blueprint('clients', __name__)

@clients_bp.route('/')
@login_required
def clients():
    """
    Renders the main clients page.
    It fetches initial client data by running 'pivpn -l' and parsing its output.
    This process is designed to fail gracefully if the command fails or parsing errors occur.
    """
    # 1. Initialize clients_data with an empty dictionary as a default.
    # If anything goes wrong during data retrieval, this empty dict will be passed to the template, preventing a crash.
    clients_data = {}

    try:
        # 2. The entire logic is enclosed in a try...except block for robust error handling.
        ansi_escape_pattern = re.compile(r'\x1B(?:[@-Z\\-_]|[0-?]*[ -/]*[@-~])')
        
        # Execute the external command. `check=True` will raise a CalledProcessError
        # if the command returns a non-zero exit code.
        result = subprocess.run(
            ['pivpn', '-l'], 
            capture_output=True, 
            text=True, 
            check=True, 
            encoding='utf-8'
        )
        
        output_lines = result.stdout.strip().split('\n')
        # Use a boolean flag for better readability than a text-based state.
        is_parsing_clients = False
        
        for line in output_lines:
            # The "Disabled clients" section marks the end of the data we are interested in.
            if '::: Disabled clients :::' in line:
                break
            
            # If we are in the correct section, process the line.
            if is_parsing_clients:
                cleaned_line = ansi_escape_pattern.sub('', line).strip()
                if not cleaned_line:
                    continue  # Skip empty lines
                
                parts = cleaned_line.split()
                if len(parts) >= 5:
                    client_name, public_key = parts[0], parts[1]
                    creation_date_str = ' '.join(parts[2:])
                    
                    # Attempt to format the date; if it fails, use the original string as a fallback.
                    try:
                        dt_obj = datetime.strptime(creation_date_str, "%a %b %d %H:%M:%S %Z %Y")
                        formatted_date = dt_obj.strftime("%Y-%m-%dT%H:%M:00")
                    except ValueError:
                        formatted_date = creation_date_str
                        
                    clients_data[client_name] = {
                        "public_key": public_key, 
                        "creation_date": formatted_date
                    }
            
            # The table header activates parsing mode for subsequent lines.
            if 'Client' in line and 'Public key' in line and 'Creation date' in line:
                is_parsing_clients = True

    # 3. Handle specific errors gracefully.
    except FileNotFoundError:
        # More specific error if the 'pivpn' command is not found.
        current_app.logger.error("'pivpn' command not found. Ensure it is installed and in the system's PATH.")
    except subprocess.CalledProcessError as e:
        # Error if the 'pivpn -l' command fails (e.g., returns a non-zero exit code).
        current_app.logger.error(f"Error executing 'pivpn -l': {e.stderr}")
    except Exception as e:
        # A catch-all for any other unexpected errors during parsing.
        current_app.logger.error(f"Unexpected error while fetching data for the clients: {e}", exc_info=True)
        
    # The function always returns the template, even in case of an error.
    # In that scenario, 'clients_data' will simply be an empty dictionary.
    return render_template('clients.html', 
                           clients_data=clients_data,
                           pivpn_subnet=current_app.config['PIVPN_NETWORK'],
                           update_interval=current_app.config['UPDATE_INTERVAL'])

@clients_bp.route('/data')
@login_required
def data():
    """API endpoint to provide the monitoring data from the log file."""
    try:
        log_file = current_app.config['LOG_FILE']
        if not os.path.exists(log_file):
            # If the log file doesn't exist yet, return empty data.
            return jsonify({"last_update": 0, "hosts": []}), 200
        with open(log_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data), 200
    except Exception as e:
        current_app.logger.error(f"API /data error: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error."}), 500

@clients_bp.route('/on_off', methods=['POST'])
@login_required
def on_off():
    """API endpoint to enable or disable a client."""
    action = 'on' if 'status' in request.form else 'off'
    client_name = request.form.get('client')
    if not client_name or not re.match(r'^[a-zA-Z0-9_-]+$', client_name):
        return jsonify({"error": "Invalid data."}), 400
    command = ['pivpn', f'-{action}', '-y', client_name]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        # Manually trigger a monitoring cycle to immediately reflect the change.
        monitor.run_monitoring_cycle(skip_updates=True)
        action_str = "enabled" if action == "on" else "disabled"
        return jsonify({"message": f"Client '{client_name}' successfully {action_str}."}), 200
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@clients_bp.route('/client_conf', methods=['GET'])
@login_required
def client_conf():
    """API endpoint to download a client's configuration file."""
    client_name = request.args.get('client')
    if not client_name or not re.match(r'^[a-zA-Z0-9_\-]+$', client_name):
        return jsonify({"message": "Invalid client name."}), 400
    try:
        file_path = os.path.join(current_app.config['WG_CLIENTS_PATH'], f"{client_name}.conf")
        return send_file(file_path, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"message": f"Configuration file for '{client_name}' not found."}), 404

@clients_bp.route('/qrcode', methods=['GET'])
@login_required
def qrcode():
    """API endpoint to generate and serve a QR code for a client's configuration."""
    client_name = request.args.get('client')
    if not client_name or not re.match(r'^[a-zA-Z0-9_-]+$', client_name):
        return jsonify({"error": "Invalid client name."}), 400
    try:
        file_path = os.path.join(current_app.config['WG_CLIENTS_PATH'], f"{client_name}.conf")
        with open(file_path, 'r', encoding='utf-8') as f:
            config = f.read()
        command = ['qrencode', '-s', '8', '-t', 'PNG', '-o', '-']
        result = subprocess.run(command, input=config.encode('utf-8'), capture_output=True, check=True)
        return send_file(io.BytesIO(result.stdout), mimetype='image/png')
    except FileNotFoundError:
        return jsonify({"error": "'qrencode' not found on the server."}), 500
    except Exception as e:
        return jsonify({"error": "Error generating QR code."}), 500

@clients_bp.route('/client_delete', methods=['POST'])
@login_required
def client_delete():
    """API endpoint to delete a client."""
    client_name = request.json.get('client')
    if not client_name or not re.match(r'^[a-zA-Z0-9_\-]+$', client_name):
        return jsonify({"error": "Invalid client name."}), 400
    command = ['pivpn', '-r', '-y', client_name]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        # Manually trigger a monitoring cycle to immediately reflect the change
        monitor.run_monitoring_cycle(skip_updates=True)
        return jsonify({"message": f"Client '{client_name}' deleted successfully."}), 200
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@clients_bp.route('/client_add', methods=['POST'])
@login_required
def client_add():
    """API endpoint to add a new client."""
    data = request.get_json()
    client_name = data.get('name')
    if not client_name or not re.match(r'^[a-zA-Z0-9_\-]+$', client_name):
        return jsonify({"message": "Invalid client name."}), 400
    
    command = ['pivpn', '-a', '-n', client_name]
    client_ip_str = data.get('ip')
    if client_ip_str and client_ip_str.lower() != 'auto':
        try:
            pivpn_net = ipaddress.ip_network(current_app.config['PIVPN_NETWORK'])
            if ipaddress.ip_address(client_ip_str) not in pivpn_net:
                 return jsonify({"message": f"The IP does not belong to the network ({pivpn_net})."}), 400
            command.extend(['-ip', client_ip_str])
        except ValueError:
            return jsonify({"message": "Invalid IP format."}), 400
    else:
        command.extend(['-ip', 'auto'])

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        output, error = result.stdout, result.stderr
        if result.returncode != 0:
            if "already exists" in (output or error):
                return jsonify({"message": f"Client '{client_name}' already exists."}), 409
            return jsonify({"message": "Error executing pivpn.", "details": error or output}), 500
        # Manually trigger a monitoring cycle to immediately reflect the change
        monitor.run_monitoring_cycle(skip_updates=True)
        return jsonify({"message": f"Client '{client_name}' added successfully."}), 201
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500