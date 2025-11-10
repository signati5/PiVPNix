#!/bin/bash

# ==============================================================================
# PiVPNix Installation and Configuration Script
# ==============================================================================
# This script automates the complete installation of PiVPNix on Debian-based systems.
# It manages system dependencies, sets up a Python virtual environment, configures
# the application, and creates a systemd service to ensure it runs at system boot.
# ==============================================================================

# --- Safety and Shell Settings ---
set -e  # Exit immediately if any command exits with a non-zero status

# --- Output Formatting (Colors) ---
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Global Variables ---
DIR_REPO=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
CONFIG_FILE="${DIR_REPO}/PiVPNix/config.ini"
REQUIREMENTS_FILE="${DIR_REPO}/requirements.txt"
VENV_DIR="${DIR_REPO}/venv"

SERVICE_NAME="pivpnix"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_PORT=""  # Will be defined by user input
APP_HOST=""  # Will be defined by user input

# --- Logging and Messaging Functions ---
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

# --- Function Definitions ---

# 1. Ensure the script is run with root privileges
check_sudo() {
    info "Checking for root privileges..."
    if [ "$EUID" -ne 0 ]; then
        error "This script must be run as root. Please use 'sudo ./install.sh'"
    fi
    info "Root privileges confirmed."
}

# 2. Update packages and install required dependencies
install_dependencies() {
    info "Updating package list and installing dependencies..."
    apt-get update > /dev/null
    
    # Install required system packages
    apt-get install -y python3-venv git qrencode
    if [ $? -ne 0 ]; then error "Failed to install required system packages."; fi
    info "Dependencies installed: python3-venv, git, qrencode."

    # Create Python virtual environment if not already present
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating Python virtual environment in ${VENV_DIR}..."
        python3 -m venv "$VENV_DIR"
        if [ $? -ne 0 ]; then error "Failed to create virtual environment."; fi
    else
        info "Virtual environment already exists."
    fi

    # Install Python dependencies from requirements.txt
    info "Installing Python packages from ${REQUIREMENTS_FILE}..."
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS_FILE"
    if [ $? -ne 0 ]; then error "Failed to install Python dependencies."; fi
    info "Python dependencies installed successfully."
}

# 3. Configure application credentials and secrets
configure_ini() {
    info "Configuring application settings..."

    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found at: ${CONFIG_FILE}"
    fi

    # Prompt for web interface credentials
    read -p "Enter a username for the web interface: " web_user
    while true; do
        read -s -p "Enter a password for user '${web_user}': " web_pass
        echo
        read -s -p "Confirm the password: " web_pass_confirm
        echo
        [ "$web_pass" = "$web_pass_confirm" ] && break
        warn "Passwords do not match. Please try again."
    done

    # Hash the password using bcrypt via the Python virtual environment
    info "Hashing password securely with bcrypt..."
    # We use 'echo -n' and pipe it to avoid the password appearing in the command history
    local hashed_password
    hashed_password=$(echo -n "$web_pass" | "$VENV_DIR/bin/python" -c "import sys, bcrypt; print(bcrypt.hashpw(sys.stdin.read().encode('utf-8'), bcrypt.gensalt()).decode('utf-8'))")

    if [ -z "$hashed_password" ]; then
        error "Failed to hash the password. Please make sure 'bcrypt' is listed in requirements.txt."
    fi

    # Escape special characters (&, /, \) in the variables for sed replacement
    local safe_hashed_password=$(printf '%s\n' "$hashed_password" | sed -e 's/[&\\/]/\\&/g')
    local safe_secret_key=$(printf '%s\n' "$secret_key" | sed -e 's/[&\\/]/\\&/g')

    # Generate a secure secret key
    info "Generating secure secret key..."
    local secret_key=$(openssl rand -hex 32)

    # Update config.ini with new credentials and key
    info "Writing credentials and secret key to ${CONFIG_FILE}..."
    sed -i -E "s/^(username\s*=\s*).*/\1${web_user}/i" "$CONFIG_FILE"
    sed -i -E "s/^(password\s*=\s*).*/\1${safe_hashed_password}/i" "$CONFIG_FILE"
    sed -i -E "s/^(secret_key\s*=\s*).*/\1${safe_secret_key}/i" "$CONFIG_FILE"

    info "Configuration file updated."

    info "Previewing updated config (hiding password):"
    grep -E "^username|^secret_key" "$CONFIG_FILE" --color=never || true
}

# 4. Prompt user for the desired web service host
ask_for_host() {
    info "Configuring listening address for the web interface..."
    echo "Do you want the interface to be accessible from:"
    echo "  1) All devices on the network (0.0.0.0) [recommended]"
    echo "  2) Only this device (localhost / 127.0.0.1) [advanced]"

    while true; do
        read -p "Choose an option [default: 1]: " -e -i 1 choice
        case "$choice" in
            1)
                APP_HOST="0.0.0.0"
                info "The interface will be accessible from the entire network."
                break
                ;;
            2)
                APP_HOST="127.0.0.1"
                info "The interface will be accessible only from localhost."
                break
                ;;
            *)
                warn "Invalid choice. Please enter 1 or 2."
                ;;
        esac
    done
}

# 5. Prompt user for the desired web service port and validate it
ask_for_port() {
    info "Configuring listening port for the web interface..."
    while true; do
        read -p "Enter the port to run the service on [default: 8001]: " -e -i 8001 user_port
        if ! [[ "$user_port" =~ ^[0-9]+$ ]] || [ "$user_port" -lt 1 ] || [ "$user_port" -gt 65535 ]; then
            warn "Invalid input. Port must be a number between 1 and 65535."
            continue
        fi
        if ss -tuln | grep -q ":${user_port} "; then
            warn "Port ${user_port} is already in use. Please choose another."
            continue
        fi
        APP_PORT=$user_port
        info "Port ${APP_PORT} is available and will be used."
        break
    done
}

# 6. Create a systemd service to automatically run PiVPNix at startup
setup_service() {
    info "Creating systemd service '${SERVICE_NAME}.service'..."

    # --- Find the path to the 'pivpn' binary dynamically ---
    info "Locating 'pivpn' command..."
    local pivpn_path=$(command -v pivpn)
    if [ -z "$pivpn_path" ]; then
        error "'pivpn' command not found. Please ensure PiVPN is properly installed."
    fi
    local pivpn_dir=$(dirname "$pivpn_path")
    info "Found 'pivpn' in: ${pivpn_dir}"

    # Define variables for service execution
    local PIVPNIX_DIR="${DIR_REPO}/PiVPNix"
    local PYTHON_EXEC="${VENV_DIR}/bin/python"
    local APP_FILE="${PIVPNIX_DIR}/app.py"

    # --- Write the service file ---
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=PiVPNix Web Interface
After=network.target wg-quick@wg0.service
BindsTo=wg-quick@wg0.service

[Service]
WorkingDirectory=${PIVPNIX_DIR}
ExecStart=${PYTHON_EXEC} ${APP_FILE} --host ${APP_HOST} --port ${APP_PORT}
User=root
Group=root
Restart=always
RestartSec=5
Environment="PATH=${VENV_DIR}/bin:${pivpn_dir}:/usr/bin:/bin:/usr/sbin:/sbin"

[Install]
WantedBy=multi-user.target
EOF

    info "Systemd service file written to ${SERVICE_FILE}."

    # Reload systemd and start the new service
    info "Reloading systemd and starting the service..."
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    systemctl restart "${SERVICE_NAME}.service"

    info "Service '${SERVICE_NAME}' started."
    sleep 3  # Wait briefly to allow the service to initialize

    # Check if the service started successfully
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        info "✅ Service is active and running."
        systemctl status "${SERVICE_NAME}.service" --no-pager
    else
        echo "Run this for detailed logs: sudo journalctl -u ${SERVICE_NAME} -b"
        error "Service failed to start. Check journal logs for more details."
    fi
}

# --- Main Execution Function ---
main() {
    echo "========================================="
    echo "        PiVPNix Automated Installer      "
    echo "========================================="
    echo

    check_sudo
    install_dependencies
    configure_ini
    ask_for_host
    ask_for_port
    setup_service

    echo
    info "========================================================================"
    info "✅ Installation complete!"
    info "The PiVPNix web interface is now running and set to launch on boot."
    info "Access the interface from another device using:"
    info "   http://$(hostname -I | awk '{print $1}'):${APP_PORT}"
    info ""
    info "Manage the service using systemd commands:"
    info "   - Check status: sudo systemctl status ${SERVICE_NAME}"
    info "   - Stop service: sudo systemctl stop ${SERVICE_NAME}"
    info "   - Start service: sudo systemctl start ${SERVICE_NAME}"
    info "========================================================================"
}

# --- Entry Point ---
main
