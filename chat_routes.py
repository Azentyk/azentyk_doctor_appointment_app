# chat_routes.py (Flask version for Azure deployment)

from flask import Blueprint, request, session, render_template, redirect, url_for, jsonify
from datetime import datetime
import logging
import time, random

from agent import get_or_create_agent_for_user, remove_agent
from db_utils import (
    patient_each_chat_table_collection,
    push_patient_information_data_to_db,
    push_patient_chat_data_to_db,update_appointment_status
)
from session import update_session_record
from patient_bot_conversational import *
from prompt import doctor_appointment_patient_data_extraction_prompt,doctor_appointment_patient_data_extraction__cancel_prompt,doctor_appointment_patient_data_extraction__rescheduled_prompt

chat_bp = Blueprint("chat", __name__)
logger = logging.getLogger(__name__)

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

    # Appointment booking trigger check
    if any(phrase in final_response for phrase in [
        'We are booking an appointment',
        'processing your doctor appointment request','currently processing your doctor appointment request',
        'processing your request','will proceed to finalize the booking','scheduling is in progress']):
        
        try:
            patient_data = doctor_appointment_patient_data_extraction_prompt(llm).invoke(str(last_message['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data: {patient_data}")

            if not isinstance(patient_data, dict):
                logger.error(f"[{session_id}] patient_data is not a dict: {patient_data}")
                return jsonify({"response": "Could not extract appointment details. Please provide your name, email, and preferred date/time."})

            required_fields = ["username", "mail", "appointment_booking_date", "appointment_booking_time", "hospital_name"]
            missing = [f for f in required_fields if f not in patient_data or not patient_data[f]]
            if missing:
                logger.error(f"[{session_id}] Missing fields in patient_data: {missing} | {patient_data}")
                return jsonify({"response": f"Missing fields: {', '.join(missing)}. Please provide them again."})
    
            patient_data['appointment_status'] = 'Pending'
            appointment_id = f"APT-{patient_data['username'][:4]}-{int(time.time())}{random.randint(1000,9999)}"
            print("Appointment ID:", appointment_id)
            # Insert appointment_id at the beginning
            appointment = {"appointment_id": appointment_id, **patient_data}

            push_patient_information_data_to_db(appointment)
            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_booked", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment booking initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.error(f"Error while booking appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while processing your appointment. Please try again."})

        return jsonify({"response": "Thank you! We are currently processing your doctor appointment request. The scheduling is in progress. You will receive a confirmation shortly."})
    


    # Appointment cancel trigger check
    if any(phrase in final_response for phrase in ['cancelled successfully','cancelled','successfully cancelled']):
        
        try:
            patient_data = doctor_appointment_patient_data_extraction__cancel_prompt(llm).invoke(str(last_message['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data: {patient_data}")

            appointment_id = patient_data['appointment_id']
            appointment_status = patient_data['appointment_status']
            update_appointment_status(appointment_id,appointment_status)

            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_cancelled", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment cancelling initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.error(f"Error while cancelling appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while cancelling your appointment. Please try again."})

        return jsonify({"response": "Your appointment has been cancelled successfully. Would you like to book or reschedule another appointment?"})
    
    # Appointment rescheduled trigger check
    if any(phrase in final_response for phrase in ['successfully rescheduled','rescheduled']):
        
        try:
            patient_data = doctor_appointment_patient_data_extraction__rescheduled_prompt(llm).invoke(str(last_message['messages']))
            logger.debug(f"[{session_id}] Extracted patient_data: {patient_data}")

            appointment_id = patient_data['appointment_id']
            appointment_status = patient_data['appointment_status']
            update_appointment_status(appointment_id,appointment_status)

            chat_df = {'patient_name': patient_data['username'], 'chat_history': str(last_message['messages'])}
            push_patient_chat_data_to_db(chat_df)

            update_session_record(session_id, "appointment_rescheduled", {
                'patient_name': patient_data['username'],
                'timestamp': str(now)
            })

            logger.info(f"[{session_id}] Appointment rescheduled initiated for patient={patient_data['username']}")
        except Exception as e:
            logger.error(f"Error while rescheduled appointment for {session_id} | {e}")
            return jsonify({"response": "We faced an issue while rescheduled your appointment. Please try again."})

        return jsonify({"response": "Your appointment has been rescheduled successfully. Would you like to book an appointment?"})




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

