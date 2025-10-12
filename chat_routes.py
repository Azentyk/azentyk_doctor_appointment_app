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


# --------------------------
# GET: Chat page
# --------------------------
@chat_bp.route("/chat/<session_id>", methods=["GET"])
def chat_page(session_id):
    if ("user" not in session or "session_id" not in session or session.get("session_id") != session_id):
        update_session_record(session_id, "unauthorized_access_attempt")
        logger.warning(f"Unauthorized access attempt for session_id={session_id}")
        return redirect(url_for("auth.login_page"))

    update_session_record(session_id, "chat_page_accessed")
    logger.info(f"Chat page accessed: session_id={session_id}, user={session.get('user')}")

    # Try to reuse last bot message saved in session
    last_message = session.get("last_bot_message")
    if last_message:
        logger.debug(f"Using last_bot_message from session for session_id={session_id}")
    else:
        # Fall back to original behavior: call graph to generate an initial greeting
        email = session.get("user")
        user_details = get_or_create_agent_for_user(email, session_id)
        logger.debug(f"user_details: {user_details}")

        initial_message = f"Hello, User Details are: {user_details['configurable']['patient_data']}"
        try:
            last_message_obj = part_1_graph.invoke(
                {"messages": ("user", initial_message)},
                config=user_details
            )
            last_message = last_message_obj['messages'][-1].content
            logger.info(f"Last message generated for session_id={session_id}: {last_message}")
            patient_each_chat_table_collection(last_message)
            # attempt to save in session for subsequent GETs
            try:
                session['last_bot_message'] = last_message
            except Exception as e:
                logger.warning(f"Could not write last_bot_message to session: {e}")
        except Exception as e:
            logger.exception(f"Failed to generate initial message for session_id={session_id}: {e}")
            last_message = "Welcome to Azentyk — how can I help you today?"

    return render_template("index.html", greeting=last_message, session_id=session_id)


# --------------------------
# POST: Chat interaction
# --------------------------
@chat_bp.route("/chat/<session_id>", methods=["POST"])
def chat(session_id):
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
        # Keep the full graph response object (used later by extractors)
        last_message_obj = part_1_graph.invoke(
            {"messages": ("user", user_input)},
            config=user_details
        )
        final_response = last_message_obj['messages'][-1].content
    except Exception as e:
        logger.error(f"Error invoking graph for {session_id} | {e}")
        return jsonify({"response": "Sorry, something went wrong while processing your request."})

    # Save bot message to session so GET route can show it without NameError
    try:
        session['last_bot_message'] = final_response
    except Exception as e:
        logger.warning(f"Could not write last_bot_message to session: {e}")

    patient_each_chat_table_collection(final_response)
    logger.info(f"[{session_id}] Bot response: {final_response}")
    update_session_record(session_id, "bot_response", {"response": final_response, "timestamp": str(now)})

    # Appointment booking trigger check
    if any(phrase in final_response for phrase in [
        'We are booking an appointment',
        'processing your doctor appointment request','currently processing your doctor appointment request',
        'processing your request','will proceed to finalize the booking','scheduling is in progress']):
        
        try:
            # Use the messages array from the full graph response for extractor
            patient_data = doctor_appointment_patient_data_extraction_prompt(llm).invoke(str(last_message_obj['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data raw: {patient_data}")

            # 1) Ensure extractor returned a dict
            if not isinstance(patient_data, dict):
                logger.error(f"[{session_id}] patient_data is not a dict: {patient_data}")
                return jsonify({"response": "Could not extract appointment details. Please provide your name, email, and preferred date/time."})

            # 2) Resolve authenticated email (cookie session preferred, fallback to header/session mapping)
            auth_email = session.get("user")
            if not auth_email:
                sid = session.get("session_id") or request.headers.get("session_id") or request.headers.get("Session-Id")
                if sid:
                    try:
                        auth_email = get_email_from_session_id(sid)
                    except Exception:
                        logger.exception(f"[{session_id}] Failed to resolve email from sid {sid}")
            logger.debug(f"[{session_id}] auth_email resolved as: {auth_email}")

            # 3) Helper to detect "use existing" style placeholders
            def _looks_like_use_existing(val):
                if not val or not isinstance(val, str):
                    return False
                lowered = val.strip().lower()
                triggers = [
                    "use existing", "use my existing", "existing email", "use the existing email",
                    "same as my account", "same email", "use my account email", "use same email",
                    "use existing one", "existing", "my account email", "yes"
                ]
                return any(t in lowered for t in triggers)
                
            # 4) Smartly fill 'mail' from session or user prompt
            mail_val = patient_data.get("mail") or patient_data.get("email")

            # Case 1: Extractor found no email. Use the authenticated session email by default.
            if not mail_val:
                if auth_email:
                    logger.debug(f"[{session_id}] Mail not found in extraction, using authenticated session email: {auth_email}")
                    patient_data['mail'] = auth_email
                else:
                    logger.warning(f"[{session_id}] Mail not found in extraction and no authenticated email session exists.")
                    return jsonify({"response": "Missing email. Please provide your email or confirm you want to use your account email."})

            # Case 2: User said "use my account email" or similar.
            elif _looks_like_use_existing(mail_val):
                if auth_email:
                    logger.debug(f"[{session_id}] User requested existing mail, using auth email '{auth_email}'")
                    patient_data['mail'] = auth_email
                else:
                    logger.warning(f"[{session_id}] User requested existing mail but no auth session found.")
                    return jsonify({"response": "You asked to use your existing email but I couldn't find your account. Please provide your email."})

            # Case 3: An explicit email was extracted, ensure it's in the 'mail' key.
            else:
                if "mail" not in patient_data:
                    patient_data['mail'] = mail_val

            # 5) Fill username and phone from contact info if missing or placeholder
            username_val = patient_data.get("username")
            if _looks_like_use_existing(username_val) or not username_val:
                if auth_email:
                    try:
                        contact_info, _ = get_user_contact_info(auth_email)
                        if contact_info and isinstance(contact_info, list) and len(contact_info) > 0:
                            firstname = contact_info[0].get("firstname")
                            phone_from_contact = contact_info[0].get("phone")
                            if firstname:
                                logger.debug(f"[{session_id}] Filling missing username from contact info: {firstname}")
                                patient_data['username'] = firstname
                            # If phone not provided by extractor, fill it too
                            if 'phone_number' not in patient_data or not patient_data.get('phone_number'):
                                if phone_from_contact:
                                    patient_data['phone_number'] = phone_from_contact
                    except Exception:
                        logger.exception(f"[{session_id}] Failed to fetch contact info for {auth_email}")

            # Final fallbacks
            if not patient_data.get('username'):
                patient_data['username'] = "User"
            if not patient_data.get('mail'):
                logger.error(f"[{session_id}] Mail still missing after fallbacks: {patient_data}")
                return jsonify({"response": "Missing email. Please provide your email or confirm you want to use your account email."})

            # 6) Now validate required fields (after fallbacks)
            required_fields = ["username", "mail", "appointment_booking_date", "appointment_booking_time", "hospital_name"]
            missing = [f for f in required_fields if f not in patient_data or not patient_data[f]]
            if missing:
                logger.error(f"[{session_id}] Missing fields in patient_data after fallbacks: {missing} | {patient_data}")
                return jsonify({"response": f"Missing fields: {', '.join(missing)}. Please provide them again."})

            # 7) All good — create appointment doc and persist
            patient_data['appointment_status'] = 'Pending'
            appointment_id = f"APT-{patient_data['username'][:4]}-{int(time.time())}{random.randint(1000,9999)}"
            logger.debug(f"[{session_id}] Generated appointment_id: {appointment_id}")

            appointment = {"appointment_id": appointment_id, **patient_data}
            logger.info(f"[{session_id}] Final appointment doc to insert: {appointment}")

            push_patient_information_data_to_db(appointment)
            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message_obj['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_booked", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment booking initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.exception(f"Error while booking appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while processing your appointment. Please try again."})

        # Return friendly confirmation (include username)
        username = patient_data.get("username", "User")
        # Send push notification to user about booking (keeps original FCM v1 behavior)
        try:
            send_push_notification_v1(user_email)
        except Exception as e:
            logger.warning(f"Failed to send booking push notification: {e}")
        return jsonify({"response": f"Thank you {username}! We are currently processing your doctor appointment request. The scheduling is in progress. You will receive a confirmation shortly."})
    

    # Appointment cancel trigger check
    if any(phrase in final_response for phrase in ['cancelled successfully','cancelled','successfully cancelled']):
        
        try:
            patient_data = doctor_appointment_patient_data_extraction__cancel_prompt(llm).invoke(str(last_message_obj['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data: {patient_data}")

            appointment_id = patient_data['appointment_id']
            appointment_status = patient_data['appointment_status']
            update_appointment_status(appointment_id,appointment_status)

            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message_obj['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_cancelled", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment cancelling initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.error(f"Error while cancelling appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while cancelling your appointment. Please try again."})

        try:
            send_push_notification_v1(user_email)
        except Exception as e:
            logger.warning(f"Failed to send cancellation push notification: {e}")
        return jsonify({"response": "Your appointment has been cancelled successfully. Would you like to book or reschedule another appointment?"})
    
    # Appointment rescheduled trigger check
    if any(phrase in final_response for phrase in ['successfully rescheduled','rescheduled']):
        
        try:
            patient_data = doctor_appointment_patient_data_extraction__rescheduled_prompt(llm).invoke(str(last_message_obj['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data: {patient_data}")

            appointment_id = patient_data['appointment_id']
            appointment_status = patient_data['appointment_status']
            update_appointment_status(appointment_id,appointment_status)

            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message_obj['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_rescheduled", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment rescheduled initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.error(f"Error while rescheduled appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while rescheduled your appointment. Please try again."})

        try:
            send_push_notification_v1(user_email)
        except Exception as e:
            logger.warning(f"Failed to send reschedule push notification: {e}")
        return jsonify({"response": "Your appointment has been rescheduled successfully. Would you like to book an appointment?"})

    # For any other general response, send a notification (preserves original behavior)
    try:
        send_push_notification_v1(user_email)
    except Exception as e:
        logger.warning(f"Failed to send general push notification: {e}")

    return jsonify({"response": final_response})


# --------------------------
# GET: Session check
# --------------------------
@chat_bp.route("/check-session", methods=["GET"])
def check_session():
    session_id = session.get("session_id")
    valid = ("user" in session and session_id is not None)
    if session_id:
        logger.info(f"Session check performed | session_id={session_id} | valid={valid}")
    else:
        logger.warning("Session check attempted without session_id")
    return jsonify({"valid": valid})
