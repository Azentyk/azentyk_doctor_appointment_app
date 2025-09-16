from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import uuid
import logging
from datetime import datetime

from db_utils import (
    authenticate_user,
    register_user,
    load_users_df,
    get_user_contact_info
)
from logger import setup_logging

# Initialize logger
setup_logging()
logger = logging.getLogger(__name__)

# Flask Blueprint (replaces FastAPI APIRouter)
auth_bp = Blueprint("auth", __name__, template_folder="templates")


@auth_bp.route("/")
def home_page():
    logger.info("Home page accessed")
    return render_template("home.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        logger.info("Register page accessed")
        return render_template("register.html")

    # POST logic
    firstname = request.form.get("firstname")
    email = request.form.get("email")
    phone = request.form.get("phone")
    country = request.form.get("country")
    state = request.form.get("state")
    location = request.form.get("location")
    city = request.form.get("city")
    password = request.form.get("password")

    error = register_user(firstname, email, phone, country, state, location, city, password)

    if error is None:
        logger.info(
            f"Registration successful for {email} from IP {request.remote_addr} "
            f"User-Agent: {request.headers.get('User-Agent', '')}"
        )
        return redirect(url_for("auth.login_page"))

    logger.warning(
        f"Registration failed for {email}. Reason: {error}. "
        f"IP: {request.remote_addr}, User-Agent: {request.headers.get('User-Agent', '')}"
    )

    flash(error, "error")
    return render_template("register.html", message=error)


@auth_bp.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        logger.info("Login page accessed")
        return render_template("login.html")

    # POST logic
    email = request.form.get("email")
    password = request.form.get("password")

    if authenticate_user(email, password):
        session_id = str(uuid.uuid4())
        session["user"] = email
        session["session_id"] = session_id

        logger.info(
            f"User {email} logged in successfully with session ID {session_id} "
            f"from IP {request.remote_addr}, User-Agent: {request.headers.get('User-Agent', '')}"
        )
        return redirect(url_for("chat.chat_page", session_id=session_id))

    logger.warning(
        f"Failed login attempt for {email} "
        f"from IP {request.remote_addr}, User-Agent: {request.headers.get('User-Agent', '')}"
    )

    flash("Invalid email or password", "error")
    return render_template("login.html", message="Invalid email or password")


@auth_bp.route("/logout")
def logout():
    session_id = session.get("session_id")
    user_email = session.get("user")

    if session_id:
        logger.info(f"User {user_email} logged out from session {session_id}")
    else:
        logger.warning("Logout attempted without active session")

    session.clear()
    return redirect(url_for("auth.home_page"))
