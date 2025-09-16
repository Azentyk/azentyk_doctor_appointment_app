import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    """Configure logging with rotating .txt file handler for Flask/Azure"""
    log_dir = os.path.join(os.getcwd(), "logs")  # ensure Azure uses correct path
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.txt")

    # Rotating text log file (app.txt, app.txt.1, etc.)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,             # keep last 5 rotated files
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)

    # Console output (important for Azure logs)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[file_handler, console_handler]
    )

    logging.info("Logging is set up successfully.")
