# authentication.py -- changes made for app
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, render_template_string
import uuid
import logging
from datetime import datetime, timedelta
import secrets
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from db_utils import (
    authenticate_user,
    register_user,
    patient_credentials_collection, # IMPORT THIS
    save_session_mapping,
    delete_session_mapping,
    update_user_password 
)
from logger import setup_logging

try:
    from session import create_session_record, update_session_record
except Exception:
    def create_session_record(*args, **kwargs): return None
    def update_session_record(*args, **kwargs): return None

setup_logging()
logger = logging.getLogger(__name__)

# --- HARDCODED CREDENTIALS FOR PASSWORD RESET ---
MAIL_USERNAME = "noreply.azentyk@gmail.com"
MAIL_APP_PASSWORD = "focuckhbyshcoisx"
# ------------------------------------------------

auth_bp = Blueprint("auth", __name__, template_folder="templates")

# --- NEW COLLECTION FOR STORING RESET TOKENS ---
from db_utils import db 
password_resets_collection = db["password_resets"]
# ------------------------------------------------

@auth_bp.route("/")
def home_page():
    logger.info("Home page accessed")
    return render_template("home.html")

# --- MODIFIED TO HANDLE BOTH WEB AND APP ---
@auth_bp.route("/register", methods=["GET", "POST"]) # <-- FIX: Added "GET"
def register_page():
    """
    Handles user registration.
    - GET: Serves the registration HTML page for web browsers.
    - POST: Handles API registration from the Flutter app.
    """
    # Handle web browser request to see the page
    if request.method == 'GET':
        logger.info("Register page accessed from web")
        return render_template("register.html") # Assumes you have a register.html template

    # Handle API request from Flutter app
    if request.method == 'POST':
        if not request.is_json:
            logger.warning(f"Registration attempt failed: Request is not JSON from IP {request.remote_addr}")
            return jsonify({"error": "Invalid request format. Must be JSON."}), 400

        data = request.get_json()
        firstname = data.get("firstname")
        email = data.get("email")
        phone = data.get("phone")
        country = data.get("country")
        state = data.get("state")
        location = data.get("location")
        city = data.get("city")
        password = data.get("password")

        if not all([firstname, email, password]):
            logger.warning(f"Registration attempt failed: Missing required fields from IP {request.remote_addr}")
            return jsonify({"error": "Missing required fields: firstname, email, and password"}), 400

        error = register_user(firstname, email, phone, country, state, location, city, password)

        if error is None:
            logger.info(f"API Registration successful for {email} from IP {request.remote_addr}")
            return jsonify({"message": "Registration successful"}), 201
        else:
            logger.warning(f"API Registration failed for {email}. Reason: {error}.")
            return jsonify({"error": error}), 400

# (The rest of your authentication.py file remains exactly the same)
# ... login_page, google_login, logout, forgot_password, etc. ...
@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        logger.info("Login page accessed")
        return render_template("login.html")

    email = request.form.get("email")
    password = request.form.get("password")

    if authenticate_user(email, password):
        session_id = str(uuid.uuid4())
        session["user"] = email
        session["session_id"] = session_id

        try:
            save_session_mapping(session_id, email)
        except Exception:
            logger.exception("Failed to save session mapping on login")

        try:
            create_session_record(request, email, session_id)
            update_session_record(session_id, "login_success")
        except Exception as e:
            logger.exception(f"Failed to create/update session record after login: {e}")

        logger.info(f"User {email} logged in successfully with session ID {session_id}")
        return redirect(url_for("chat.chat_page", session_id=session_id))

    try:
        update_session_record(None, "login_failed", {'email': email})
    except Exception as e:
        logger.exception(f"Failed to update session record for login_failed: {e}")

    logger.warning(f"Failed login attempt for {email}")
    flash("Invalid email or password", "error")
    return render_template("login.html", message="Invalid email or password")

# --- REWRITTEN GOOGLE LOGIN ROUTE ---
@auth_bp.route("/google-login", methods=["POST"])
def google_login():
    data = request.form
    email = data.get("email")
    firstname = data.get("firstname")
    logger.info(f"Google login attempt for {email}")

    if not email or not firstname:
        return jsonify({"error": "Email and firstname are required"}), 400

    user_document = patient_credentials_collection.find_one({"email": email})
    
    if not user_document:
        logger.info(f"User {email} not found. Auto-registering now...")
        error = register_user(
            firstname=firstname,
            email=email,
            phone="-",
            country="-", state="-", location="-", city="-",
            password="google_oauth",
        )
        if error:
            logger.error(f"Auto-registration failed for {email}: {error}")
            return jsonify({"error": "Google login failed during user creation"}), 500
        
        user_document = patient_credentials_collection.find_one({"email": email})

    session_id = str(uuid.uuid4())
    session["user"] = email
    session["session_id"] = session_id
    save_session_mapping(session_id, email)
    
    logger.info(f"Google login successful for {email}")

    return jsonify({
        "message": "Login successful",
        "session_id": session_id,
        "isProfileComplete": user_document.get("isProfileComplete", True)
    })

# --- NEW ROUTE FOR COMPLETING USER PROFILE ---
@auth_bp.route("/api/complete-profile", methods=["POST"])
def complete_profile():
    if "user" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    email = session["user"]
    data = request.form
    phone = data.get("phone")
    firstname = data.get("firstname")

    if not phone or not firstname:
        return jsonify({"error": "Phone number and firstname are required"}), 400

    try:
        patient_credentials_collection.update_one(
            {"email": email},
            {"$set": {
                "phone": phone,
                "firstname": firstname,
                "isProfileComplete": True
            }}
        )
        logger.info(f"Profile completed for user {email}")
        return jsonify({"message": "Profile updated successfully"}), 200
    except Exception as e:
        logger.exception(f"Failed to update profile for {email}: {e}")
        return jsonify({"error": "Database update failed"}), 500

@auth_bp.route("/logout")
def logout():
    session_id = session.get("session_id")
    user_email = session.get("user")

    if session_id:
        logger.info(f"User {user_email} logged out from session {session_id}")
    else:
        logger.warning("Logout attempted without active session")

    if session_id:
        try:
            update_session_record(session_id, "logout")
        except Exception as e:
            logger.exception(f"Failed to update session record for logout: {e}")

    if session_id:
        try:
            delete_session_mapping(session_id)
        except Exception:
            logger.exception(f"Failed to delete session mapping for {session_id}")

    session.clear()
    return redirect(url_for("auth.home_page"))


# --- NEW ROUTES FOR PASSWORD RESET ---

@auth_bp.route("/api/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json()
    email = data.get("email")
    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = patient_credentials_collection.find_one({"email": email})
    if not user:
        return jsonify({"message": "If an account with that email exists, a reset link has been sent."}), 200

    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(minutes=15)

    password_resets_collection.insert_one({
        "email": email,
        "token": token,
        "expires_at": expiry
    })

    reset_link = url_for('auth.reset_password_page', token=token, _external=True)
    
    sender_email = MAIL_USERNAME
    receiver_email = email
    password = MAIL_APP_PASSWORD

    message = MIMEMultipart("alternative")
    message["Subject"] = "Reset Your Password"
    message["From"] = sender_email
    message["To"] = receiver_email

    text = f"Hi,\nClick the link to reset your password: {reset_link}"
    html = f"""
    <html><body>
        <p>Hi,<br>Please click the button below to reset your password. This link is valid for 15 minutes.</p>
        <a href="{reset_link}" style="background-color: #4CAF50; color: white; padding: 14px 25px; text-align: center; text-decoration: none; display: inline-block;">Reset Password</a>
    </body></html>
    """
    message.attach(MIMEText(text, "plain"))
    message.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, message.as_string())
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
        return jsonify({"error": "Could not send reset email."}), 500

    return jsonify({"message": "If an account with that email exists, a reset link has been sent."}), 200


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_page():
    if request.method == "GET":
        token = request.args.get('token')
        reset_request = password_resets_collection.find_one({"token": token})

        if not reset_request or reset_request['expires_at'] < datetime.utcnow():
            error_template = "<h2>Invalid or Expired Link</h2><p>Your password reset link is invalid or has expired. Please request a new one.</p>"
            return render_template_string(error_template), 400

        reset_form_template = """
        <!DOCTYPE html><html><head><title>Reset Password</title>
        <style>body{font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;background-color:#f4f4f4}form{background:white;padding:2rem;border-radius:8px;box-shadow:0 4px 6px rgba(0,0,0,0.1)}input{width:100%;padding:0.5rem;margin-bottom:1rem;border:1px solid #ccc;border-radius:4px}button{width:100%;padding:0.7rem;background-color:#007bff;color:white;border:none;border-radius:4px;cursor:pointer}</style>
        </head><body>
            <form action="{{ url_for('auth.reset_password_page') }}" method="post">
                <h2>Choose a New Password</h2>
                <input type="hidden" name="token" value="{{ token }}">
                <label for="password">New Password:</label><br>
                <input type="password" id="password" name="password" required><br>
                <label for="confirm_password">Confirm New Password:</label><br>
                <input type="password" id="confirm_password" name="confirm_password" required><br>
                <button type="submit">Reset Password</button>
            </form>
        </body></html>
        """
        return render_template_string(reset_form_template, token=token)

    if request.method == "POST":
        token = request.form.get('token')
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            error_template = "<h2>Passwords Do Not Match</h2><p>Please go back and try again.</p>"
            return render_template_string(error_template), 400
        
        reset_request = password_resets_collection.find_one({"token": token})
        if not reset_request or reset_request['expires_at'] < datetime.utcnow():
            error_template = "<h2>Invalid or Expired Link</h2><p>Your password reset link is invalid or has expired. Please request a new one.</p>"
            return render_template_string(error_template), 400

        success = update_user_password(reset_request['email'], new_password)
        
        if success:
            password_resets_collection.delete_one({"token": token})
            success_template = "<h2>Success!</h2><p>Your password has been updated. You can now return to the app and log in with your new password.</p>"
            return render_template_string(success_template)
        else:
            error_template = "<h2>Error</h2><p>An error occurred while updating your password. Please try again.</p>"
            return render_template_string(error_template), 500
