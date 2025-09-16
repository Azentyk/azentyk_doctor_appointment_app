from datetime import datetime
from typing import Optional
import re

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone: str) -> bool:
    """Validate phone number format (10 digits)"""
    return phone.isdigit() and len(phone) == 10

def get_current_datetime() -> str:
    """Return current datetime as string"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def clean_input(text: str) -> Optional[str]:
    """Clean and sanitize user input"""
    if not text or not isinstance(text, str):
        return None
    return text.strip()