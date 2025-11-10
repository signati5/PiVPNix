# web/config_manager.py

import os
import re
import shutil
from datetime import datetime
from flask import Blueprint, render_template, current_app, request, jsonify

# Import our custom decorator
from .auth import login_required

config_bp = Blueprint('config_manager', __name__)

def _get_allowed_files():
    """
    Dynamically discovers and returns a dictionary of manageable configuration files.
    This function scans predefined paths for PiVPN, WireGuard server, and
    WireGuard client configuration files.
    """
    pivpn_file = current_app.config['PIVPN_CONFIGS_FILE']
    wg_clients_path = current_app.config['WG_CLIENTS_PATH']
    # Use the dedicated path for server configurations
    wg_server_path = current_app.config['WG_SERVER_CONFIG_PATH']
    
    allowed_files = {}
    
    # 1. Add the main PiVPN setup file (if it exists)
    if os.path.exists(pivpn_file):
        allowed_files['pivpn_setup'] = {
            'path': pivpn_file,
            'description': 'Main PiVPN setup configuration',
            'category': 'service'
        }

    # 2. Dynamically add WireGuard server configuration files
    try:
        if os.path.isdir(wg_server_path):
            for filename in sorted(os.listdir(wg_server_path)):
                # Check if it's a .conf file and NOT a directory
                full_path = os.path.join(wg_server_path, filename)
                if filename.endswith('.conf') and os.path.isfile(full_path):
                    interface_name = os.path.splitext(filename)[0]
                    key = f'wg_server_{interface_name}'
                    allowed_files[key] = {
                        'path': full_path,
                        'description': f'Server configuration: {interface_name} interface',
                        'category': 'service'
                    }
    except FileNotFoundError:
        current_app.logger.warning(f"WireGuard server directory '{wg_server_path}' not found.")

    # 3. Dynamically add WireGuard client configuration files
    try:
        if os.path.isdir(wg_clients_path):
            for filename in sorted(os.listdir(wg_clients_path)):
                if filename.endswith('.conf'):
                    client_name = os.path.splitext(filename)[0]
                    key = f'wg_client_{client_name}'
                    allowed_files[key] = {
                        'path': os.path.join(wg_clients_path, filename),
                        'description': f'Client configuration: {client_name}',
                        'category': 'client'
                    }
    except FileNotFoundError:
        current_app.logger.warning(f"WireGuard client directory '{wg_clients_path}' not found.")
        
    return allowed_files

@config_bp.route('/')
@login_required
def manager():
    """Renders the main configuration manager page."""
    files = _get_allowed_files()
    
    # Group files by category for rendering in the template
    config_files_grouped = {
        'service': {'title': 'Service Configurations', 'files': {}},
        'client': {'title': 'Client Configurations', 'files': {}}
    }
    for key, data in files.items():
        # Default to 'client' category if not specified
        category = data.get('category', 'client') 
        config_files_grouped[category]['files'][key] = data
        
    return render_template('config_manager.html', config_files_grouped=config_files_grouped)


# --- API Endpoints ---

@config_bp.route('/api/view')
@login_required
def view_config():
    """Returns the content of a specific configuration file."""
    file_key = request.args.get('file_key')
    allowed_files = _get_allowed_files()

    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403

    file_path = allowed_files[file_key]['path']

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    except FileNotFoundError:
        return jsonify({"error": f"File '{os.path.basename(file_path)}' not found."}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading file {file_path}: {e}")
        return jsonify({"error": "Error while reading the file."}), 500


@config_bp.route('/api/save', methods=['POST'])
@login_required
def save_config():
    """Saves changes to a configuration file after creating a backup."""
    data = request.get_json()
    file_key = data.get('file_key')
    content = data.get('content')
    
    if not file_key or content is None:
        return jsonify({"error": "Missing data."}), 400

    allowed_files = _get_allowed_files()
    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403

    file_path = allowed_files[file_key]['path']

    # 1. Create the backup
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{file_path}.bak.{timestamp}"
        shutil.copy2(file_path, backup_path) # copy2 preserves metadata
    except Exception as e:
        current_app.logger.error(f"Error creating backup for {file_path}: {e}")
        return jsonify({"error": "Could not create backup. Save operation cancelled."}), 500

    # 2. Save the new content
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"message": f"File '{os.path.basename(file_path)}' saved successfully. Backup created at '{os.path.basename(backup_path)}'."}), 200
    except Exception as e:
        current_app.logger.error(f"Error saving file {file_path}: {e}")
        # Attempt to restore from backup if the write fails
        shutil.move(backup_path, file_path)
        return jsonify({"error": "Error while saving the file. The backup has been restored."}), 500

        
# --- Backup Management APIs ---

@config_bp.route('/api/backups')
@login_required
def list_backups():
    """Lists the backup files for a given file_key."""
    file_key = request.args.get('file_key')
    allowed_files = _get_allowed_files()

    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403

    file_path = allowed_files[file_key]['path']
    directory = os.path.dirname(file_path)
    base_filename = os.path.basename(file_path)
    
    backups = []
    try:
        for filename in sorted(os.listdir(directory), reverse=True):
            # Look for files that start with the base filename and contain ".bak."
            if filename.startswith(base_filename) and ".bak." in filename:
                # Extract the timestamp from the filename
                match = re.search(r'\.bak\.(\d{8}_\d{6})$', filename)
                if match:
                    timestamp_str = match.group(1)
                    try:
                        # Format the timestamp into a human-readable format
                        dt_object = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                        readable_date = dt_object.strftime('%d %b %Y, %H:%M:%S')
                        backups.append({
                            "filename": filename,
                            "date": readable_date
                        })
                    except ValueError:
                        # The format doesn't match, but we add it anyway
                        backups.append({"filename": filename, "date": "Unrecognized date"})

        return jsonify(backups)
    except Exception as e:
        current_app.logger.error(f"Error listing backups for {file_path}: {e}")
        return jsonify({"error": "Could not list backups."}), 500


@config_bp.route('/api/restore', methods=['POST'])
@login_required
def restore_backup():
    """Restores a file from one of its backups."""
    data = request.get_json()
    file_key = data.get('file_key')
    backup_filename = data.get('backup_filename')

    if not file_key or not backup_filename:
        return jsonify({"error": "Missing data."}), 400

    allowed_files = _get_allowed_files()
    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403

    original_path = allowed_files[file_key]['path']
    directory = os.path.dirname(original_path)
    backup_path = os.path.join(directory, backup_filename)

    # Sanity check: ensure the backup belongs to the original file
    if not backup_filename.startswith(os.path.basename(original_path) + ".bak."):
        return jsonify({"error": "Invalid backup name."}), 400
    if not os.path.exists(backup_path):
        return jsonify({"error": "Backup file not found."}), 404

    try:
        # We restore by copying, so the original backup file is not lost
        shutil.copy2(backup_path, original_path)
        return jsonify({"message": f"File successfully restored from backup '{backup_filename}'."})
    except Exception as e:
        current_app.logger.error(f"Error restoring from {backup_path}: {e}")
        return jsonify({"error": "An error occurred during restoration."}), 500


@config_bp.route('/api/delete_backup', methods=['POST'])
@login_required
def delete_backup():
    """Deletes a backup file."""
    data = request.get_json()
    file_key = data.get('file_key')
    backup_filename = data.get('backup_filename')

    if not file_key or not backup_filename:
        return jsonify({"error": "Missing data."}), 400

    allowed_files = _get_allowed_files()
    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403
        
    original_path = allowed_files[file_key]['path']
    directory = os.path.dirname(original_path)
    backup_path = os.path.join(directory, backup_filename)

    # Same security checks as the restore function
    if not backup_filename.startswith(os.path.basename(original_path) + ".bak."):
        return jsonify({"error": "Invalid backup name."}), 400
    if not os.path.exists(backup_path):
        return jsonify({"error": "Backup file not found."}), 404

    try:
        os.remove(backup_path)
        return jsonify({"message": f"Backup '{backup_filename}' deleted successfully."})
    except Exception as e:
        current_app.logger.error(f"Error deleting {backup_path}: {e}")
        return jsonify({"error": "An error occurred while deleting the backup."}), 500


@config_bp.route('/api/view_backup')
@login_required
def view_backup():
    """Returns the content of a specific backup file."""
    file_key = request.args.get('file_key')
    backup_filename = request.args.get('backup_filename')

    if not file_key or not backup_filename:
        return jsonify({"error": "Missing data."}), 400

    allowed_files = _get_allowed_files()
    if file_key not in allowed_files:
        return jsonify({"error": "File access not permitted."}), 403
        
    original_path = allowed_files[file_key]['path']
    directory = os.path.dirname(original_path)
    backup_path = os.path.join(directory, backup_filename)

    # Security checks to prevent Path Traversal attacks
    if not backup_filename.startswith(os.path.basename(original_path) + ".bak."):
        return jsonify({"error": "Invalid backup name."}), 400
    
    # Normalize paths for a safe comparison
    safe_directory = os.path.realpath(directory)
    safe_backup_path = os.path.realpath(backup_path)
    
    if not safe_backup_path.startswith(safe_directory):
         return jsonify({"error": "Attempted to access a disallowed path."}), 403

    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content})
    except FileNotFoundError:
        return jsonify({"error": "Backup file not found."}), 404
    except Exception as e:
        current_app.logger.error(f"Error reading backup {backup_path}: {e}")
        return jsonify({"error": "Error reading the backup file."}), 500