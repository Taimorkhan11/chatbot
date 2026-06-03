import azure.functions as func
import json
import os
import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta
from azure.cosmos import CosmosClient
import anthropic
from dotenv import load_dotenv

load_dotenv()

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "chatbot-db")
USERS_CONTAINER = os.getenv("COSMOS_USERS_CONTAINER", "users")
MESSAGES_CONTAINER = os.getenv("COSMOS_MESSAGES_CONTAINER", "messages")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 24))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin@123")

def get_containers():
    client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
    database = client.get_database_client(COSMOS_DATABASE)
    return (
        database.get_container_client(USERS_CONTAINER),
        database.get_container_client(MESSAGES_CONTAINER)
    )

def get_anthropic():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def generate_token(user_id, username, role):
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def validate_token(req):
    auth_header = req.headers.get("Authorization", "")
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

def json_response(data, status_code=200):
    return func.HttpResponse(
        json.dumps(data),
        status_code=status_code,
        mimetype="application/json"
    )

@app.route(route="api/health", methods=["GET", "POST"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return json_response({"status": "ok", "message": "Chatbot API is running on Azure!"})

@app.route(route="api/mgmt/login", methods=["GET", "POST"])
def admin_login(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "GET":
        return json_response({"message": "Admin login endpoint - use POST"})
    try:
        body = req.get_json()
        if body.get("username") != ADMIN_USERNAME or body.get("password") != ADMIN_PASSWORD:
            return json_response({"error": "Invalid credentials"}, 401)
        token = generate_token("admin", ADMIN_USERNAME, "admin")
        return json_response({"token": token, "role": "admin"})
    except Exception as e:
        return json_response({"error": f"Login failed: {str(e)}"}, 500)

@app.route(route="api/user/login", methods=["GET", "POST"])
def user_login(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "GET":
        return json_response({"message": "User login endpoint - use POST"})
    try:
        body = req.get_json()
        username = body.get("username", "")
        password = body.get("password", "")
        users_container, _ = get_containers()
        query = f"SELECT * FROM c WHERE c.username = '{username}' AND c.role = 'user'"
        items = list(users_container.query_items(
            query=query, enable_cross_partition_query=True))
        if not items:
            return json_response({"error": "Invalid credentials"}, 401)
        user = items[0]
        if user.get("status") == "disabled":
            return json_response({"error": "Account disabled"}, 403)
        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return json_response({"error": "Invalid credentials"}, 401)
        token = generate_token(user["id"], username, "user")
        return json_response({"token": token, "role": "user"})
    except Exception as e:
        return json_response({"error": f"Login failed: {str(e)}"}, 500)

@app.route(route="api/mgmt/create-user", methods=["GET", "POST"])
def create_user(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "GET":
        return json_response({"message": "Create user endpoint - use POST"})
    decoded, error = validate_token(req)
    if error:
        return json_response({"error": error}, 401)
    if decoded.get("role") != "admin":
        return json_response({"error": "Admin access required"}, 403)
    try:
        body = req.get_json()
        username = body.get("username", "").strip()
        password = body.get("password", "").strip()
        if not username or not password:
            return json_response({"error": "Username and password required"}, 400)
        user_id = str(uuid.uuid4())
        users_container, _ = get_containers()
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
        return json_response({"message": f"User '{username}' created", "user_id": user_id})
    except Exception as e:
        return json_response({"error": f"Failed to create user: {str(e)}"}, 500)

@app.route(route="api/chat", methods=["GET", "POST"])
def chat(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "GET":
        return json_response({"message": "Chat endpoint - use POST"})
    decoded, error = validate_token(req)
    if error:
        return json_response({"error": error}, 401)
    try:
        body = req.get_json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id", "default")
        if not message:
            return json_response({"error": "Message required"}, 400)
        if len(message) > 2000:
            return json_response({"error": "Message too long"}, 400)
        user_id = decoded["user_id"]
        users_container, messages_container = get_containers()
        query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' AND c.session_id = '{session_id}' ORDER BY c.timestamp ASC OFFSET 0 LIMIT 10"
        history = list(messages_container.query_items(
            query=query, enable_cross_partition_query=True))
        messages_list = []
        for h in history:
            messages_list.append({"role": "user", "content": h["user_message"]})
            messages_list.append({"role": "assistant", "content": h["assistant_response"]})
        messages_list.append({"role": "user", "content": message})
        claude_client = get_anthropic()
        response = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="You are a helpful assistant.",
            messages=messages_list
        )
        assistant_reply = response.content[0].text
        messages_container.create_item({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "user_message": message,
            "assistant_response": assistant_reply,
            "timestamp": datetime.utcnow().isoformat()
        })
        return json_response({"response": assistant_reply, "session_id": session_id})
    except Exception as e:
        return json_response({"error": str(e)}, 500)

@app.route(route="api/chat/history", methods=["GET", "POST"])
def chat_history(req: func.HttpRequest) -> func.HttpResponse:
    decoded, error = validate_token(req)
    if error:
        return json_response({"error": error}, 401)
    try:
        user_id = decoded["user_id"]
        session_id = req.params.get("session_id", "default")
        _, messages_container = get_containers()
        query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' AND c.session_id = '{session_id}' ORDER BY c.timestamp ASC"
        history = list(messages_container.query_items(
            query=query, enable_cross_partition_query=True))
        return json_response({"history": history, "count": len(history)})
    except Exception as e:
        return json_response({"error": f"Failed to get history: {str(e)}"}, 500)