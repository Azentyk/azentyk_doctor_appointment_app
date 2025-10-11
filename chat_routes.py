# chat_routes.py (Flask version for Azure deployment)
from flask import Blueprint, request, session, render_template, redirect, url_for, jsonify
from datetime import datetime
import logging
import time, random
import os       # --- NEW ---
import requests # --- NEW ---

from agent import get_or_create_agent_for_user, remove_agent
from db_utils import (
    patient_each_chat_table_collection,
    push_patient_information_data_to_db,
    push_patient_chat_data_to_db,
    update_appointment_status,
    get_email_from_session_id,
    get_user_contact_info,
    update_user_fcm_token, # --- NEW --- Import the function to update the token
    get_fcm_token_for_user,  # --- NEW --- Import the function to get the token
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


# --- NEW --- Helper function to send push notifications
def send_push_notification(user_email):
    """
    Retrieves a user's FCM token and sends a generic push notification.
    """
    logger.info(f"Attempting to send generic notification to user: {user_email}")

    # 1. Get the FCM Token from your Database
    try:
        fcm_token = get_fcm_token_for_user(user_email)
        if not fcm_token:
            logger.warning(f"No FCM token found for user {user_email}. Cannot send notification.")
            return
    except Exception as e:
        logger.error(f"Database error while retrieving FCM token for {user_email}: {e}")
        return

    # 2. Get your Firebase Server Key from environment variables for security
    server_key = os.getenv('FIREBASE_SERVER_KEY')
    if not server_key:
        logger.error("FIREBASE_SERVER_KEY is not set in environment variables. Cannot send notification.")
        return

    # 3. Construct and Send the Request to FCM
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'key={server_key}',
    }
    payload = {
        'to': fcm_token,
        'notification': {
            'title': 'New Message from Azentyk',
            'body': 'You have a new response from the chatbot. Open the app to view it.',
            'sound': 'default'
        },
        'data': {
            'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            'screen': 'chat'
        }
    }
    try:
        response = requests.post('https://fcm.googleapis.com/fcm/send', headers=headers, json=payload)
        if response.status_code == 200:
            logger.info(f"Successfully sent generic notification to {user_email}")
        else:
            logger.error(f"Failed to send generic notification. Status: {response.status_code}, Response: {response.text}")
    except Exception as e:
        logger.error(f"Exception while sending generic notification to FCM: {e}")


# --- NEW --- API endpoint for the Flutter app to save the FCM token
@chat_bp.route("/api/user/update-fcm-token", methods=["POST"])
def update_fcm_token_route():
    # 1. Make sure the user is logged in
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user_email = session.get("user")

    # 2. Get the token from the request
    data = request.get_json()
    fcm_token = data.get("fcmToken")
    if not fcm_token:
        return jsonify({"error": "Missing fcmToken"}), 400

    # 3. Call your database function to save it
    try:
        update_user_fcm_token(user_email, fcm_token)
        return jsonify({"message": "Token updated successfully"}), 200
    except Exception as e:
        logger.error(f"Failed to update FCM token for {user_email}: {e}")
        return jsonify({"error": "Database update failed"}), 500


# --------------------------
# GET: Chat page
# --------------------------
@chat_bp.route("/chat/<session_id>", methods=["GET"])
def chat_page(session_id):
    # ... (this function remains unchanged)
    if ("user" not in session or "session_id" not in session or session.get("session_id") != session_id):
        update_session_record(session_id, "unauthorized_access_attempt")
        logger.warning(f"Unauthorized access attempt for session_id={session_id}")
        return redirect(url_for("auth.login_page"))
    update_session_record(session_id, "chat_page_accessed")
    logger.info(f"Chat page accessed: session_id={session_id}, user={session.get('user')}")
    email = session.get("user")
    user_details = get_or_create_agent_for_user(email, session_id)
    logger.debug(f"user_details: {user_details}")
    initial_message = f"Hello, User Details are: {user_details['configurable']['patient_data']}"
    last_message = part_1_graph.invoke(
        {"messages": ("user", initial_message)},
        config=user_details
    )
    last_message = last_message['messages'][-1].content
    logger.info(f"Last message generated for session_id={session_id}: {last_message}")
    patient_each_chat_table_collection(last_message)
    return render_template("index.html", greeting=last_message, session_id=session_id)


# --------------------------
# POST: Chat interaction
# --------------------------
@chat_bp.route("/chat/<session_id>", methods=["POST"])
def chat(session_id):
    # ... (most of this function is the same, with one new line at the end of each logical block)
    if ("user" not in session or "session_id" not in session or session.get("session_id") != session_id):
        logger.warning(f"Unauthorized chat attempt | session_id={session_id}")
        update_session_record(session_id, "unauthorized_chat_attempt")
        return jsonify({"response": "Invalid session. Please log in again."})

    user_email = session.get("user")
    user_input = request.json.get("user_input", "").strip()

    patient_each_chat_table_collection(user_input)
    now = datetime.now()

    logger.info(f"[{session_id}] User ({user_email}) input: {user_input}")
    update_session_record(session_id, "user_message", {"message": user_input, "timestamp": str(now)})

    user_details = get_or_create_agent_for_user(user_email, session_id)

    try:
        last_message = part_1_graph.invoke(
            {"messages": ("user", user_input)},
            config=user_details
        )
        final_response = last_message['messages'][-1].content
    except Exception as e:
        logger.error(f"Error invoking graph for {session_id} | {e}")
        return jsonify({"response": "Sorry, something went wrong while processing your request."})

    patient_each_chat_table_collection(final_response)
    logger.info(f"[{session_id}] Bot response: {final_response}")
    update_session_record(session_id, "bot_response", {"response": final_response, "timestamp": str(now)})

    # ... (The large block for appointment logic is here)
    # Appointment booking trigger check
    if any(phrase in final_response for phrase in [
        'We are booking an appointment',
        'processing your doctor appointment request','currently processing your doctor appointment request',
        'processing your request','will proceed to finalize the booking','scheduling is in progress']):
        
        # ... (all the logic to extract patient_data)
        try:
            #...
            #... LOTS OF YOUR EXISTING LOGIC FOR BOOKING ...
            #...
            
            # --- NEW --- Send notification before returning the response
            send_push_notification(user_email)
            username = patient_data.get("username", "User")
            return jsonify({"response": f"Thank you {username}! We are currently processing your doctor appointment request. The scheduling is in progress. You will receive a confirmation shortly."})
        except Exception as e:
            logger.exception(f"Error while booking appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while processing your appointment. Please try again."})


    # Appointment cancel trigger check
    if any(phrase in final_response for phrase in ['cancelled successfully','cancelled','successfully cancelled']):
        # ... (all your logic for cancellation)
        try:
            #...
            # --- NEW --- Send notification before returning the response
            send_push_notification(user_email)
            return jsonify({"response": "Your appointment has been cancelled successfully. Would you like to book or reschedule another appointment?"})
        except Exception as e:
            #...
            return jsonify({"response": "We faced an issue while cancelling your appointment. Please try again."})
    
    # Appointment rescheduled trigger check
    if any(phrase in final_response for phrase in ['successfully rescheduled','rescheduled']):
        # ... (all your logic for rescheduling)
        try:
            #...
            # --- NEW --- Send notification before returning the response
            send_push_notification(user_email)
            return jsonify({"response": "Your appointment has been rescheduled successfully. Would you like to book an appointment?"})
        except Exception as e:
            #...
            return jsonify({"response": "We faced an issue while rescheduled your appointment. Please try again."})

    # --- NEW --- Send notification for a general response
    send_push_notification(user_email)
    return jsonify({"response": final_response})


# --------------------------
# GET: Session check
# --------------------------
@chat_bp.route("/check-session", methods=["GET"])
def check_session():
    # ... (this function remains unchanged)
    session_id = session.get("session_id")
    valid = ("user" in session and session_id is not None)
    if session_id:
        logger.info(f"Session check performed | session_id={session_id} | valid={valid}")
    else:
        logger.warning("Session check attempted without session_id")
    return jsonify({"valid": valid})
