# app.py

import os
import sys
import configparser
import threading
import argparse  # Module for parsing command-line arguments
from flask import Flask
from datetime import timedelta

# Import local modules
from monitor import start_monitor
from web.auth import auth_bp
from web.clients import clients_bp
from web.dashboard import dashboard_bp
from web.config_manager import config_bp
from web.service_manager import service_bp

# --- Global Constants ---
CONFIG_FILE = "config.ini"
LOG_FILE = "data/log_traffic.json" 

def check_root():
    """Checks if the script is being run with root privileges. Exits if not."""
    if os.geteuid() != 0:
        print("\n[ERROR] This script requires root privileges to run.")
        print(f"  Please run it with sudo: sudo python3 {sys.argv[0]}\n")
        sys.exit(1)

def load_pivpn_config(config_file_path):
    """
    Reads the PiVPN configuration file (setupVars.conf) to extract
    the network address and subnet class.

    :param config_file_path: Path to the setupVars.conf file.
    :return: A tuple containing (pivpn_net, subnet_class).
    :raises ValueError: If the file is not found or required keys are missing.
    """
    pivpn_net = None
    subnet_class = None

    if not os.path.exists(config_file_path):
        raise ValueError(f"PiVPN configuration file not found: '{config_file_path}'")

    try:
        with open(config_file_path, 'r') as f:
            for line in f:
                if line.startswith('pivpnNET='):
                    pivpn_net = line.strip().split('=')[1]
                elif line.startswith('subnetClass='):
                    subnet_class = line.strip().split('=')[1]
    except IOError as e:
        raise ValueError(f"I/O error while reading '{config_file_path}': {e}")

    if not pivpn_net or not subnet_class:
        raise ValueError(f"'pivpnNET' and/or 'subnetClass' keys not found in '{config_file_path}'")

    return pivpn_net, subnet_class

def create_app():
    """
    Creates and configures the Flask application instance.
    This is the application factory.
    """
    print("[APP] Creating and configuring the Flask application instance...")
    
    app = Flask(__name__)

    config_abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)

    parser = configparser.ConfigParser()
    if not os.path.exists(config_abs_path):
        print(f"[ERROR] Configuration file '{config_abs_path}' not found.")
        sys.exit(1)
        
    parser.read(config_abs_path)
    
    try:
        # --- Flask Application Settings ---
        app.config['SECRET_KEY'] = parser.get('FLASK_SETTINGS', 'SECRET_KEY')
        print(f"secret key {parser.get('FLASK_SETTINGS', 'SECRET_KEY')}")
        app.config['USERNAME'] = parser.get('FLASK_SETTINGS', 'USERNAME')
        app.config['PASSWORD'] = parser.get('FLASK_SETTINGS', 'PASSWORD') 
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
        
        # --- Monitor Settings ---
        monitor_settings = parser['LOG_TRAFFIC_SETTINGS']
        app.config['LOG_FILE'] = config_abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_FILE)
        app.config['UPDATE_INTERVAL'] = monitor_settings.getint('interval_seconds', 30)
        app.config['HISTORY_SIZE'] = monitor_settings.getint('history_size', 120)
        app.config['IDLE_FOR_SIZE'] = monitor_settings.getint('idle_for_size', 5)
        
        not_conn_base = monitor_settings.getint('not_conn_for_size', 10)
        app.config['NOT_CONN_FOR_SIZE'] = not_conn_base + app.config['IDLE_FOR_SIZE']

        # --- System Path Configuration ---
        app.config['WG_CLIENTS_PATH'] = '/etc/wireguard/configs'
        app.config['WG_SERVER_CONFIG_PATH'] = '/etc/wireguard'
        app.config['PIVPN_CONFIGS_FILE'] = '/etc/pivpn/wireguard/setupVars.conf'
        # Load PiVPN network settings and format them into CIDR notation
        app.config['PIVPN_NETWORK'] = '{}/{}'.format(*load_pivpn_config(app.config['PIVPN_CONFIGS_FILE']))

    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        print(f"[ERROR] Error in configuration file '{config_abs_path}': {e}")
        sys.exit(1)

    # --- Register Blueprints ---
    # Each blueprint represents a logical section of the application.
    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp, url_prefix='/clients')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(config_bp, url_prefix='/config')
    app.register_blueprint(service_bp, url_prefix='/services')

    return app

if __name__ == "__main__":
    # --- Command-line argument parsing ---
    parser = argparse.ArgumentParser(description="Starts the web server for the WireGuard panel.")
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='The IP address for the server to listen on (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8001,
                        help='The port for the server to listen on (default: 8001)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable Flask\'s debug mode (enables auto-reloading and more verbose logging)')

    args = parser.parse_args() # Read the provided arguments

    # --- Application Startup ---
    check_root()
    print("Starting the WireGuard Dashboard application...")
    app = create_app()

    # Start the background monitoring thread
    # start_monitor(app)

    print(f"[WEB] Flask server started. Access it at http://{args.host}:{args.port}")
    if args.debug:
        print("[WEB] WARNING: Debug mode is active. Do not use in a production environment!")

    # Use the parsed arguments to run the server
    app.run(host=args.host, port=args.port, debug=args.debug)
