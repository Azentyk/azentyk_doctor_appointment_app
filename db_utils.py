# db_utils.py
from typing import Optional, List, Dict, Tuple
from datetime import datetime
import hashlib
import pandas as pd
from pymongo import MongoClient
import logging

# Initialize MongoDB client
client = MongoClient(
    "our mongo db URl in this place",
    tls=True,
    tlsAllowInvalidCertificates=False,
)
db = client["patient_db"]

# Collections
patient_information_details_table_collection = db["patient_information_details_table"]
patient_chat_table_collection = db["patient_chat_table"]
chat_collection = db["patient_each_chat_table"]
patient_credentials_collection = db["patient_credentials"]
sessions_collection = db["sessions"]

logger = logging.getLogger(__name__)

def init_db():
    pass

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def load_users_df() -> pd.DataFrame:
    try:
        cursor = patient_credentials_collection.find({})
        users_data = list(cursor)
        df = pd.DataFrame(users_data)
        if '_id' in df.columns:
            df.drop('_id', axis=1, inplace=True)
        expected_columns = ["firstname", "email", "phone", "country", "state", "location", "city", "password"]
        for col in expected_columns:
            if col not in df.columns:
                df[col] = None
        logger.info(f"Successfully loaded {len(df)} users from MongoDB")
        return df
    except Exception as e:
        logger.error(f"Error loading users from MongoDB: {str(e)}")
        return pd.DataFrame(columns=["firstname", "email", "phone", "country", "state", "location", "city", "password"])

def load_users_appointment_details() -> pd.DataFrame:
    try:
        cursor = patient_information_details_table_collection.find({})
        users_data = list(cursor)
        df = pd.DataFrame(users_data)
        if '_id' in df.columns:
            df.drop('_id', axis=1, inplace=True)
        expected_columns = ["appointment_id", "username", "phone_number", "mail", "location", "hospital_name", "specialization", "appointment_booking_date","appointment_booking_time","appointment_status"]
        for col in expected_columns:
            if col not in df.columns:
                df[col] = None
        return df
    except Exception as e:
        return pd.DataFrame(columns=["appointment_id", "username", "phone_number", "mail", "location", "hospital_name", "specialization", "appointment_booking_date","appointment_booking_time","appointment_status"])

def authenticate_user(email: str, password: str) -> bool:
    try:
        hashed = hash_password(password)
        user = patient_credentials_collection.find_one({"email": email, "password": hashed})
        logger.info(f"Authentication attempt for {email}: {'success' if user else 'failed'}")
        return user is not None
    except Exception as e:
        logger.error(f"Authentication error for {email}: {e}")
        return False

def register_user(firstname: str, email: str, phone: str, country: str,
                 state: str, location: str, city: str, password: str) -> Optional[str]:
    """Register a new user in the database"""
    try:
        if patient_credentials_collection.find_one({"email": email}):
            logger.warning(f"Registration failed - email already exists: {email}")
            return "Email already registered."
        if phone and phone != "-" and patient_credentials_collection.find_one({"phone": phone}):
            logger.warning(f"Registration failed - phone already exists: {phone}")
            return "Phone number already registered."

        # MODIFIED: Only hash password if it's not a Google SSO login
        hashed = hash_password(password) if password != "google_oauth" else None
        now = datetime.now()
        
        user_document = {
            "firstname": firstname,
            "email": email,
            "phone": phone,
            "country": country,
            "state": state,
            "location": location,
            "city": city,
            "password": hashed,
            "created_at": str(now),
            # MODIFIED: Set profile status based on registration type
            "isProfileComplete": False if password == "google_oauth" else True
        }

        patient_credentials_collection.insert_one(user_document)
        logger.info(f"New user registered: {email}")
        return None
    except Exception as e:
        logger.error(f"Registration error for {email}: {e}")
        return "Registration failed. Please try again."

def get_user_contact_info(email: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    try:
        df = load_users_df()
        ele_user_id = df[df['email'] == email]
        appointment_df = load_users_appointment_details()
        ele_user_appointment_df = appointment_df[appointment_df['mail'] == email]
        print(f"🔎 Found {len(ele_user_appointment_df)} appointments for {email}")
        contact_info = ele_user_id[["firstname", "email", "phone"]]
        return (
            contact_info.to_dict(orient="records"),
            ele_user_appointment_df.to_dict(orient="records")
        )
    except Exception as e:
        print(f"❌ Error in get_user_contact_info: {e}")
        return [], []

def push_patient_information_data_to_db(patient_data: dict):
    try:
        now = datetime.now()
        patient_data['date'] = str(now.strftime("%Y-%m-%d"))
        patient_data['time'] = str(now.strftime("%H:%M:%S"))
        insert_result = patient_information_details_table_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Information Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting patient information: {e}")
        return None

def push_patient_chat_data_to_db(patient_data: dict):
    try:
        now = datetime.now()
        patient_data['date'] = str(now.strftime("%Y-%m-%d"))
        patient_data['time'] = str(now.strftime("%H:%M:%S"))
        insert_result = patient_chat_table_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Chat Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting patient chat data: {e}")
        return None

def patient_each_chat_table_collection(message_text: str):
    try:
        now = datetime.now()
        patient_data = {
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'message': message_text.strip()
        }
        insert_result = chat_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Chat Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting chat message: {e}")
        return None

def get_user_appointments_by_email(email: str) -> List[Dict]:
    try:
        cursor = patient_information_details_table_collection.find({"mail": email})
        items = [doc for doc in cursor]
        for doc in items:
            doc.pop("_id", None)
        logger.info(f"Fetched {len(items)} appointments for {email}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching appointments for {email}: {e}")
        return []

def save_session_mapping(session_id: str, email: str) -> None:
    try:
        now = datetime.now().isoformat()
        sessions_collection.update_one(
            {"session_id": session_id},
            {"$set": {"email": email, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        logger.info(f"Saved session mapping for {session_id} -> {email}")
    except Exception as e:
        logger.exception(f"Failed to save session mapping: {e}")

def get_email_from_session_id(session_id: str) -> Optional[str]:
    try:
        doc = sessions_collection.find_one({"session_id": session_id})
        return doc.get("email") if doc else None
    except Exception as e:
        logger.exception(f"Failed to lookup session mapping for {session_id}: {e}")
        return None

def delete_session_mapping(session_id: str) -> None:
    try:
        sessions_collection.delete_one({"session_id": session_id})
        logger.info(f"Deleted session mapping for {session_id}")
    except Exception as e:
        logger.exception(f"Failed to delete session mapping: {e}")

def update_appointment_status(appointment_id: str, new_status: str) -> dict:
    result = patient_information_details_table_collection.update_one(
        {"appointment_id": appointment_id},
        {"$set": {"appointment_status": new_status}}
    )
    if result.modified_count > 0:
        return {"success": True, "message": f"Appointment {appointment_id} updated to '{new_status}'"}
    elif result.matched_count > 0:
        return {"success": False, "message": f"Appointment {appointment_id} already has status '{new_status}'"}
    else:
        return {"success": False, "message": f"No appointment found with ID {appointment_id}"}
