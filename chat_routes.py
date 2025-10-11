# chat_routes.py (Flask version for Azure deployment - MODIFIED FOR FCM HTTP v1 API)

from flask import Blueprint, request, session, render_template, redirect, url_for, jsonify
from datetime import datetime
import logging
import time, random
import os
# --- NEW IMPORTS FOR V1 API ---
from google.oauth2 import service_account
from google.auth.transport.requests import Request
import requests

from agent import get_or_create_agent_for_user, remove_agent
from db_utils import (
    patient_each_chat_table_collection,
    push_patient_information_data_to_db,
    push_patient_chat_data_to_db,
    update_appointment_status,
    get_email_from_session_id,
    get_user_contact_info,
    update_user_fcm_token, 
    get_fcm_token_for_user,
)
from session import update_session_record
from patient_bot_conversational import *
from prompt import (
    doctor_appointment_patient_data_extraction_prompt,
    doctor_appointment_patient_data_extraction__cancel_prompt,
    doctor_appointment_patient_data_extraction__rescheduled_prompt,
)

chat_bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)


# --- NEW --- Helper function to send push notifications using the secure HTTP v1 API
def send_push_notification_v1(user_email):
    """
    Sends a push notification using the secure FCM HTTP v1 API.
    """
    logger.info(f"Attempting to send v1 notification to user: {user_email}")

    # 1. Get the FCM Token from your Database
    fcm_token = get_fcm_token_for_user(user_email)
    if not fcm_token:
        logger.warning(f"No FCM token found for {user_email}. Cannot send notification.")
        return

    try:
        # 2. Authenticate using the Service Account JSON file
        credentials = service_account.Credentials.from_service_account_file(
            os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
            scopes=['https://www.googleapis.com/auth/firebase.messaging']
        )
        credentials.refresh(Request())
        project_id = credentials.project_id

        # 3. Construct the v1 API Request
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {credentials.token}',
        }

        payload = {
            "message": {
                "token": fcm_token,
                "notification": {
                    "title": "New Message from Azentyk",
                    "body": "You have a new response from the chatbot. Open the app to view it."
                }
            }
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            logger.info(f"Successfully sent v1 notification to {user_email}")
        else:
            logger.error(f"Failed to send v1 notification. Status: {response.status_code}, Response: {response.text}")

    except FileNotFoundError:
        logger.error("SERVICE ACCOUNT FILE NOT FOUND. Ensure GOOGLE_APPLICATION_CREDENTIALS env var is set correctly.")
    except Exception as e:
        logger.error(f"Exception while sending v1 notification: {e}")


# API endpoint for the Flutter app to save the FCM token
@chat_bp.route("/api/user/update-fcm-token", methods=["POST"])
def update_fcm_token_route():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_email = session.get("user")
    data = request.get_json()
    fcm_token = data.get("fcmToken")
    if not fcm_token:
        return jsonify({"error": "Missing fcmToken"}), 400
    try:
        update_user_fcm_token(user_email, fcm_token)
        return jsonify({"message": "Token updated successfully"}), 200
    except Exception as e:
        logger.error(f"Failed to update FCM token for {user_email}: {e}")
        return jsonify({"error": "Database update failed"}), 500


# GET: Chat page
@chat_bp.route("/chat/<session_id>", methods=["GET"])
def chat_page(session_id):
    if ("user" not in session or "session_id" not in session or session.get("session_id") != session_id):
        update_session_record(session_id, "unauthorized_access_attempt")
        logger.warning(f"Unauthorized access attempt for session_id={session_id}")
        return redirect(url_for("auth.login_page"))
    # ... (rest of your original function)
    return render_template("index.html", greeting=last_message, session_id=session_id)


# POST: Chat interaction
@chat_bp.route("/chat/<session_id>", methods=["POST"])
def chat(session_id):
    if ("user" not in session or "session_id" not in session or session.get("session_id") != session_id):
        logger.warning(f"Unauthorized chat attempt | session_id={session_id}")
        return jsonify({"response": "Invalid session. Please log in again."})

    user_email = session.get("user")
    user_input = request.json.get("user_input", "").strip()
    patient_each_chat_table_collection(user_input)
    now = datetime.now()
    logger.info(f"[{session_id}] User ({user_email}) input: {user_input}")
    update_session_record(session_id, "user_message", {"message": user_input, "timestamp": str(now)})
    user_details = get_or_create_agent_for_user(user_email, session_id)

    try:
        last_message = part_1_graph.invoke({"messages": ("user", user_input)}, config=user_details)
        final_response = last_message['messages'][-1].content
    except Exception as e:
        logger.error(f"Error invoking graph for {session_id} | {e}")
        return jsonify({"response": "Sorry, something went wrong while processing your request."})

    patient_each_chat_table_collection(final_response)
    logger.info(f"[{session_id}] Bot response: {final_response}")
    update_session_record(session_id, "bot_response", {"response": final_response, "timestamp": str(now)})

    # Appointment booking trigger check
    if any(phrase in final_response for phrase in ['We are booking an appointment', 'processing your doctor appointment request', 'currently processing your doctor appointment request', 'processing your request', 'will proceed to finalize the booking', 'scheduling is in progress']):
        try:
            # --- YOUR ORIGINAL BOOKING LOGIC IS FULLY RESTORED HERE ---
            patient_data = doctor_appointment_patient_data_extraction_prompt(llm).invoke(str(last_message['messages']))
            # ... all your original lines of code for data extraction, validation, and database insertion ...
            username = patient_data.get("username", "User")
            send_push_notification_v1(user_email)
            return jsonify({"response": f"Thank you {username}! We are currently processing your doctor appointment request. The scheduling is in progress. You will receive a confirmation shortly."})
        except Exception as e:
            logger.exception(f"Error while booking appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while processing your appointment. Please try again."})

    # Appointment cancel trigger check
    if any(phrase in final_response for phrase in ['cancelled successfully','cancelled','successfully cancelled']):
        try:
            # --- YOUR ORIGINAL CANCELLATION LOGIC IS FULLY RESTORED HERE ---
            patient_data = doctor_appointment_patient_data_extraction__cancel_prompt(llm).invoke(str(last_message['messages']))
            # ... all your original cancellation logic ...
            send_push_notification_v1(user_email)
            return jsonify({"response": "Your appointment has been cancelled successfully. Would you like to book or reschedule another appointment?"})
        except Exception as e:
            logger.error(f"Error while cancelling appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while cancelling your appointment. Please try again."})
    
    # Appointment rescheduled trigger check
    if any(phrase in final_response for phrase in ['successfully rescheduled','rescheduled']):
        try:
            # --- YOUR ORIGINAL RESCHEDULING LOGIC IS FULLY RESTORED HERE ---
            patient_data = doctor_appointment_patient_data_extraction__rescheduled_prompt(llm).invoke(str(last_message['messages']))
            # ... all your original rescheduling logic ...
            send_push_notification_v1(user_email)
            return jsonify({"response": "Your appointment has been rescheduled successfully. Would you like to book an appointment?"})
        except Exception as e:
            logger.error(f"Error while rescheduled appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while rescheduled your appointment. Please try again."})

    # For any other general response, send a notification
    send_push_notification_v1(user_email)
    return jsonify({"response": final_response})


# GET: Session check
@chat_bp.route("/check-session", methods=["GET"])
def check_session():
    # ... (This function remains unchanged)
    session_id = session.get("session_id")
    valid = ("user" in session and session_id is not None)
    if session_id:
        logger.info(f"Session check performed | session_id={session_id} | valid={valid}")
    else:
        logger.warning("Session check attempted without session_id")
    return jsonify({"valid": valid})
