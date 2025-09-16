# main.py
import os
import sys
import pysqlite3
sys.modules["sqlite3"]=pysqlite3
from flask import Flask, render_template, session
from flask_session import Session
from logger import setup_logging
from db_utils import init_db
from chat_routes import chat_bp
from authentication import auth_bp

def create_app():
    # Initialize Flask app
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Secret key (required for session management)
    app.secret_key = os.getenv("SECRET_KEY", "your_secret_key")

    # Configure session for server-side storage
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = os.path.join(os.getcwd(), "flask_session")
    app.config["SESSION_PERMANENT"] = False
    Session(app)

    # Initialize logging
    setup_logging()

    # Initialize database
    init_db()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)

    # Default route (renders index.html with session_id injected)
    @app.route("/")
    def index():
        # ensure a session exists
        if "session_id" not in session:
            session["session_id"] = os.urandom(16).hex()
        return render_template("index.html", session_id=session["session_id"])

    return app


app = create_app()

# Azure entry point
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Azure sets PORT env var
    app.run(host="0.0.0.0", port=port, debug=True)



