# Security Policy for PiVPNix

We appreciate the efforts of security researchers and our community in helping us maintain a secure product. This document outlines our security philosophy and provides guidance for users and researchers.

## Reporting a Vulnerability

We take all security reports seriously. If you believe you have found a security vulnerability in PiVPNix, we encourage you to report it to us privately.

**Please DO NOT report security vulnerabilities through public GitHub issues.**

Instead, please send an email to:
**[ricocariof@gmail.com]**

Please include the following in your report so we can better understand and resolve the issue:
*   A clear description of the vulnerability and its potential impact.
*   Detailed steps to reproduce the issue.
*   Any proof-of-concept code, screenshots, or logs that demonstrate the vulnerability.

We will make every effort to acknowledge your report within 48-72 hours and will work with you to ensure the issue is addressed promptly.

## User Security Best Practices

PiVPNix is a powerful administrative tool that interacts with your system's network configuration. To ensure your system remains secure, please follow these essential best practices.

### 1. Change Default Credentials
The installation script requires you to set a username and password. **You MUST use strong, unique credentials**. Do not use default or easily guessable passwords like "admin", "password", or "raspberry".

### 2. Use a Strong `SECRET_KEY`
The `SECRET_KEY` in `config.ini` is used by Flask to sign session cookies, preventing users from tampering with them. The installation script generates a secure random key for you. If you ever need to change it manually, use a long, unpredictable string.

### 3. Critical: Network Exposure
This is the most important security consideration for PiVPNix.

#### ✅ Recommended Method: Local Network Access Only
PiVPNix is **designed and intended for use on a trusted local network (LAN)**. The most secure way to access the panel is from a computer that is already connected to your home network, or by connecting to your VPN first and then accessing the panel through the VPN tunnel.

#### ❌ Highly Discouraged: Direct Internet Exposure
**You should NOT expose the PiVPNix web interface directly to the public internet.** Do not configure port forwarding on your router to make the panel accessible from anywhere. Doing so exposes your server's management interface to potential attacks and is extremely risky.

If you absolutely require remote access, you must implement additional security layers, such as placing the application behind a secure reverse proxy (like Nginx) with its own robust authentication mechanism (e.g., HTTP Basic Auth, Authelia, OAuth2) and firewall rules. This is an advanced configuration and should only be attempted by experienced users.

### 4. Keep Your System Updated
PiVPNix runs on your server's operating system (e.g., Raspberry Pi OS). Keeping the underlying system and all its packages (including PiVPN itself) up to date is crucial for overall security. Regularly run these commands:
```bash
sudo apt update && sudo apt upgrade -y
```

## Project Security Measures

We have implemented the following measures within the PiVPNix codebase to enhance security:

*   **Limited Command Execution**: The application interacts with the system using specific, predefined shell commands (`pivpn`, `systemctl`, `wg`). User-provided input (like client names) is validated with regular expressions to prevent command injection attacks.
*   **No Direct Shell Access**: The web interface does not provide a general-purpose shell or terminal.
*   **Virtual Environment**: The installation script sets up a Python virtual environment (`venv`) to isolate application dependencies from system packages, which is a security and stability best practice.
*   **Session-Based Authentication**: Access is protected by a login system that uses secure, signed session cookies.

Thank you for helping keep PiVPNix and its community secure.
