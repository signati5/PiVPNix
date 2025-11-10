# web/auth.py

from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify

# Create the Blueprint for authentication
auth_bp = Blueprint('auth', __name__)

# --- Authentication Decorator ---
def login_required(f):
    """
    A decorator to protect routes that require a user to be logged in.
    If the user is not logged in, it redirects them to the login page.
    For API requests, it returns a 401 Unauthorized error.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            # If the request is for an API, respond with JSON
            if request.path.startswith('/api/'):
                return jsonify({"error": "Authentication required"}), 401
            # Otherwise, redirect to the login page
            return redirect(url_for('auth.login'))
        # If the user is logged in, execute the original view function
        return f(*args, **kwargs)
    return decorated_function

# --- Authentication Routes ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles the login process.
    GET: Displays the login form.
    POST: Validates credentials and logs the user in.
    """
    # If the user is already logged in, redirect to the dashboard page
    if 'logged_in' in session:
        return redirect(url_for('dashboard.dashboard')) # Redirects to the 'dashboard' function of the 'dashboard' blueprint

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Get the stored credentials from the application configuration
        stored_username = current_app.config['USERNAME']
        stored_password = current_app.config['PASSWORD']
        
        # Check if the provided credentials are valid
        if username == stored_username and password == stored_password:
            session['logged_in'] = True
            session.permanent = True # Makes the session persistent across browser restarts
            return redirect(url_for('dashboard.dashboard'))
        else:
            # If credentials are invalid, show an error message
            flash('Invalid credentials. Please try again.')
    
    # For a GET request, just render the login page
    return render_template('login.html')

@auth_bp.route('/')
def root():    
    """Redirects the application's root URL to the login page."""
    return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    session.pop('logged_in', None) # Remove 'logged_in' key from the session
    return redirect(url_for('auth.login'))