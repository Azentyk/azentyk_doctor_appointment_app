# authentication.py -- changes made for app
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import uuid
import logging
from datetime import datetime

from db_utils import (
    authenticate_user,
    register_user,
    patient_credentials_collection, # IMPORT THIS
    save_session_mapping,
    delete_session_mapping
)
from logger import setup_logging

try:
    from session import create_session_record, update_session_record
except Exception:
    def create_session_record(*args, **kwargs): return None
    def update_session_record(*args, **kwargs): return None

setup_logging()
logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, template_folder="templates")

@auth_bp.route("/")
def home_page():
    logger.info("Home page accessed")
    return render_template("home.html")

# --- MODIFIED FOR FLUTTER APP ---
@auth_bp.route("/register", methods=["POST"])
def register_page():
    """
    API endpoint for user registration.
    Accepts a JSON payload and returns a JSON response.
    """
    if not request.is_json:
        logger.warning(f"Registration attempt failed: Request is not JSON from IP {request.remote_addr}")
        return jsonify({"error": "Invalid request format. Must be JSON."}), 400

    data = request.get_json()

    # Get data from the JSON payload
    firstname = data.get("firstname")
    email = data.get("email")
    phone = data.get("phone")
    country = data.get("country")
    state = data.get("state")
    location = data.get("location")
    city = data.get("city")
    password = data.get("password")

    # Basic validation
    if not all([firstname, email, password]):
        logger.warning(f"Registration attempt failed: Missing required fields from IP {request.remote_addr}")
        return jsonify({"error": "Missing required fields: firstname, email, and password"}), 400

    error = register_user(firstname, email, phone, country, state, location, city, password)

    if error is None:
        logger.info(f"API Registration successful for {email} from IP {request.remote_addr}")
        # Return a JSON success message with a 201 Created status code
        return jsonify({"message": "Registration successful"}), 201
    else:
        logger.warning(f"API Registration failed for {email}. Reason: {error}.")
        # Return a JSON error message with a 400 Bad Request status code
        return jsonify({"error": error}), 400

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
    """
    Accepts POST with 'email' and 'firstname'.
    Finds the user or creates them if they don't exist.
    Returns session_id and their profile completion status.
    """
    data = request.form
    email = data.get("email")
    firstname = data.get("firstname")
    logger.info(f"Google login attempt for {email}")

    if not email or not firstname:
        return jsonify({"error": "Email and firstname are required"}), 400

    # More efficient check: find user directly from the collection
    user_document = patient_credentials_collection.find_one({"email": email})
    
    # If user doesn't exist, register them
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

    # Create session
    session_id = str(uuid.uuid4())
    session["user"] = email
    session["session_id"] = session_id
    save_session_mapping(session_id, email)
    
    logger.info(f"Google login successful for {email}")

    # Return session_id AND the profile status flag
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
