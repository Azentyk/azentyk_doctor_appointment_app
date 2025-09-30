
from flask import Blueprint, session, jsonify
import logging
from db_utils import get_user_appointments_by_email

logger = logging.getLogger(__name__)
appointments_bp = Blueprint("appointments", __name__)

@appointments_bp.route("/appointments", methods=["GET"])
def list_appointments():
    user_email = session.get("user")
    if not user_email:
        return jsonify({"error": "unauthenticated"}), 401
    try:
        appts = get_user_appointments_by_email(user_email)
        return jsonify({"appointments": appts}), 200
    except Exception as e:
        logger.exception("Failed to fetch appointments")
        return jsonify({"error": "server_error"}), 500
