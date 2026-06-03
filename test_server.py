from flask import Flask, request, jsonify
import os
import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta
from azure.cosmos import CosmosClient
#from openai import OpenAI
from groq import Groq

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# CONFIG
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "chatbot-db")
USERS_CONTAINER = os.getenv("COSMOS_USERS_CONTAINER", "users")
MESSAGES_CONTAINER = os.getenv("COSMOS_MESSAGES_CONTAINER", "messages")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 24))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@123")

# CLIENTS
cosmos_client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
db = cosmos_client.get_database_client(COSMOS_DATABASE)
users_container = db.get_container_client(USERS_CONTAINER)
messages_container = db.get_container_client(MESSAGES_CONTAINER)
# openai_client = OpenAI(api_key=OPENAI_API_KEY)
openai_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# HELPERS
def generate_token(user_id, username, role):
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def validate_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Missing token"
    token = auth_header.split(" ")[1]
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return decoded, None
    except jwt.ExpiredSignatureError:
        return None, "Token expired"
    except jwt.InvalidTokenError:
        return None, "Invalid token"

# ROUTES
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Chatbot API is running"})

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    body = request.get_json()
    if body.get("username") != ADMIN_USERNAME or body.get("password") != ADMIN_PASSWORD:
        return jsonify({"error": "Invalid credentials"}), 401
    token = generate_token("admin", ADMIN_USERNAME, "admin")
    return jsonify({"token": token, "role": "admin"})

@app.route("/api/user/login", methods=["POST"])
def user_login():
    body = request.get_json()
    username = body.get("username", "")
    password = body.get("password", "")
    query = f"SELECT * FROM c WHERE c.username = '{username}' AND c.role = 'user'"
    items = list(users_container.query_items(
        query=query, enable_cross_partition_query=True))
    if not items:
        return jsonify({"error": "Invalid credentials"}), 401
    user = items[0]
    if user.get("status") == "disabled":
        return jsonify({"error": "Account disabled"}), 403
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify({"error": "Invalid credentials"}), 401
    token = generate_token(user["id"], username, "user")
    return jsonify({"token": token, "role": "user"})

@app.route("/api/admin/create-user", methods=["POST"])
def create_user():
    decoded, error = validate_token()
    if error:
        return jsonify({"error": error}), 401
    if decoded.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    body = request.get_json()
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    user_id = str(uuid.uuid4())
    user_record = {
        "id": user_id,
        "username": username,
        "password_hash": bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()).decode(),
        "role": "user",
        "status": "active",
        "created_at": datetime.utcnow().isoformat(),
        "last_login": None
    }
    users_container.create_item(user_record)
    return jsonify({
        "message": f"User '{username}' created successfully",
        "user_id": user_id
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    decoded, error = validate_token()
    if error:
        return jsonify({"error": error}), 401
    body = request.get_json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "default")
    if not message:
        return jsonify({"error": "Message required"}), 400
    if len(message) > 2000:
        return jsonify({"error": "Message too long"}), 400
    user_id = decoded["user_id"]

    # Load chat history
    query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' AND c.session_id = '{session_id}' ORDER BY c.timestamp ASC OFFSET 0 LIMIT 10"
    history = list(messages_container.query_items(
        query=query, enable_cross_partition_query=True))

    messages_list = [{"role": "system", "content": "You are a helpful assistant."}]
    for h in history:
        messages_list.append({"role": "user", "content": h["user_message"]})
        messages_list.append({"role": "assistant", "content": h["assistant_response"]})
    messages_list.append({"role": "user", "content": message})

    # Call OpenAI
    response = openai_client.chat.completions.create(
        #model="gpt-3.5-turbo",
        model="llama-3.3-70b-versatile",
        messages=messages_list,
        max_tokens=500
    )
    assistant_reply = response.choices[0].message.content

    # Save to Cosmos DB
    messages_container.create_item({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "session_id": session_id,
        "user_message": message,
        "assistant_response": assistant_reply,
        "timestamp": datetime.utcnow().isoformat()
    })
    return jsonify({"response": assistant_reply, "session_id": session_id})

@app.route("/api/chat/history", methods=["GET"])
def chat_history():
    decoded, error = validate_token()
    if error:
        return jsonify({"error": error}), 401
    user_id = decoded["user_id"]
    session_id = request.args.get("session_id", "default")
    query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' AND c.session_id = '{session_id}' ORDER BY c.timestamp ASC"
    history = list(messages_container.query_items(
        query=query, enable_cross_partition_query=True))
    return jsonify({"history": history, "count": len(history)})

if __name__ == "__main__":
    app.run(port=7071, debug=True)