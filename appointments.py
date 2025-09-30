from flask import Blueprint, session, jsonify, request
import logging
from db_utils import get_user_appointments_by_email, get_email_from_session_id

logger = logging.getLogger(__name__)
appointments_bp = Blueprint("appointments", __name__)

@appointments_bp.route("/appointments", methods=["GET"])
def list_appointments():
    # 1) Prefer server-side cookie/session
    user_email = session.get("user")

    # 2) Fallback: accept session_id header from mobile clients
    if not user_email:
        sid = (
            request.headers.get("session_id")
            or request.headers.get("Session-Id")
            or request.headers.get("x-session-id")
        )
        if sid:
            user_email = get_email_from_session_id(sid)

    if not user_email:
        return jsonify({"error": "unauthenticated"}), 401

    try:
        appts = get_user_appointments_by_email(user_email)
        return jsonify({"appointments": appts}), 200
    except Exception as e:
        logger.exception("Failed to fetch appointments")
        return jsonify({"error": "server_error"}), 500

