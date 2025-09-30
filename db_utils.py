from typing import Optional, List, Dict
from datetime import datetime
import hashlib
import pandas as pd
from pymongo import MongoClient
import logging
from typing import Optional, List, Dict,Tuple

# Initialize MongoDB client
# client = MongoClient("mongodb://localhost:27017/")
# client = MongoClient("mongodb+srv://azentyk:azentyk123@cluster0.b9aaq47.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
client = MongoClient("mongodb://azentyk-doctor-appointment-app-server:ROtcf6VzE2Jj2Etn0D3QY9LbrSTs4MEgld2hynMw3R46gl8cuL1D70qvx4DjQvogoyBDVO2z1MJxACDb04M0BA==@azentyk-doctor-appointment-app-server.mongo.cosmos.azure.com:10255/?ssl=true&retrywrites=false&replicaSet=globaldb&maxIdleTimeMS=120000&appName=@azentyk-doctor-appointment-app-server@",tls=True, tlsAllowInvalidCertificates=False)
db = client["patient_db"]

# Collections
patient_information_details_table_collection = db["patient_information_details_table"]
patient_chat_table_collection = db["patient_chat_table"]
chat_collection = db["patient_each_chat_table"]
patient_credentials_collection = db["patient_credentials"]

logger = logging.getLogger(__name__)

def init_db():
    """Initialize database collections if they don't exist"""
    # This will create collections automatically when data is first inserted
    pass

def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def load_users_df() -> pd.DataFrame:
    """Load users from MongoDB and return as DataFrame"""
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
    """Load users from MongoDB and return as DataFrame"""
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
                
        # logger.info(f"Successfully loaded {len(df)} users from MongoDB")
        return df
    
    except Exception as e:
        # logger.error(f"Error loading users from MongoDB: {str(e)}")
        return pd.DataFrame(columns=["appointment_id", "username", "phone_number", "mail", "location", "hospital_name", "specialization", "appointment_booking_date","appointment_booking_time","appointment_status"])


def authenticate_user(email: str, password: str) -> bool:
    """Return True if email/password match a document in MongoDB."""
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
        # Check if email or phone already exists
        if patient_credentials_collection.find_one({"email": email}):
            logger.warning(f"Registration failed - email already exists: {email}")
            return "Email already registered."
        if patient_credentials_collection.find_one({"phone": phone}):
            logger.warning(f"Registration failed - phone already exists: {phone}")
            return "Phone number already registered."

        # Hash the password
        hashed = hash_password(password)

        now = datetime.now()
        # Create the user document
        user_document = {
            "firstname": firstname,
            "email": email,
            "phone": phone,
            "country": country,
            "state": state,
            "location": location,
            "city": city,
            "password": hashed,
            "created_at": str(now)
        }

        # Insert into MongoDB
        patient_credentials_collection.insert_one(user_document)
        logger.info(f"New user registered: {email}")
        return None  # Success
    except Exception as e:
        logger.error(f"Registration error for {email}: {e}")
        return "Registration failed. Please try again."


def get_user_contact_info(email: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Get user contact information and all appointments by email"""
    try:
        # Load user credentials
        df = load_users_df()
        ele_user_id = df[df['email'] == email]
        
        # Load all appointment details
        appointment_df = load_users_appointment_details()
        ele_user_appointment_df = appointment_df[appointment_df['mail'] == email]
        
        print(f"🔎 Found {len(ele_user_appointment_df)} appointments for {email}")
        
        # Extract contact info
        contact_info = ele_user_id[["firstname", "email", "phone"]]
        
        # Return contact info + all appointments (dynamic length)
        return (
            contact_info.to_dict(orient="records"),
            ele_user_appointment_df.to_dict(orient="records")
        )
    except Exception as e:
        print(f"❌ Error in get_user_contact_info: {e}")
        return [], []
    
def push_patient_information_data_to_db(patient_data: dict):
    """Insert patient information into database"""
    try:
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        patient_data['date'] = str(current_date)
        patient_data['time'] = str(current_time)

        insert_result = patient_information_details_table_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Information Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting patient information: {e}")
        return None

def push_patient_chat_data_to_db(patient_data: dict):
    """Insert patient chat data into database"""
    try:
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        patient_data['date'] = str(current_date)
        patient_data['time'] = str(current_time)

        insert_result = patient_chat_table_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Chat Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting patient chat data: {e}")
        return None

def patient_each_chat_table_collection(message_text: str):
    """Insert individual chat message into database"""
    try:
        now = datetime.now()
        current_date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M:%S")

        patient_data = {
            'date': current_date,
            'time': current_time,
            'message': message_text.strip()
        }

        insert_result = chat_collection.insert_one(patient_data)
        logger.info(f"Inserted Patient Chat Data ID: {insert_result.inserted_id}")
        return insert_result
    except Exception as e:
        logger.error(f"Error inserting chat message: {e}")
        return None

def get_user_appointments_by_email(email: str) -> List[Dict]:
    """Return list of appointment dicts for the given email (mail column)."""
    try:
        cursor = patient_information_details_table_collection.find({"mail": email})
        items = []
        for doc in cursor:
            doc.pop("_id", None)  # remove _id so JSON works
            items.append(doc)
        logger.info(f"Fetched {len(items)} appointments for {email}")
        return items
    except Exception as e:
        logger.exception(f"Error fetching appointments for {email}: {e}")
        return []

def update_appointment_status(appointment_id: str, new_status: str) -> dict:
    """
    Update the appointment_status for a patient record in MongoDB
    based on the appointment_id.

    Args:
        appointment_id (str): The appointment ID to match
        new_status (str): The new status value ("booking in progress", "confirmed", "pending","rescheduled","cancelled")

    Returns:
        dict: A summary of the update result
    """
    result = patient_information_details_table_collection.update_one(
        {"appointment_id": appointment_id},   # filter by appointment_id
        {"$set": {"appointment_status": new_status}}  # update the status
    )

    if result.modified_count > 0:
        return {"success": True, "message": f"Appointment {appointment_id} updated to '{new_status}'"}
    elif result.matched_count > 0:
        return {"success": False, "message": f"Appointment {appointment_id} already has status '{new_status}'"}
    else:

        return {"success": False, "message": f"No appointment found with ID {appointment_id}"}

