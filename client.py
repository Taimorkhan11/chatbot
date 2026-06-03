import requests
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("FUNCTION_URL", "http://localhost:7071/api")
token = None
current_role = None
session_id = "session-1"

def set_headers():
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def parse_response(res):
    if not res.text.strip():
        print(f"❌ Empty response from server (HTTP {res.status_code})")
        print(f"   URL: {res.url}")
        return None
    try:
        return res.json()
    except Exception:
        print(f"❌ Non-JSON response (HTTP {res.status_code}): {res.text[:300]}")
        return None

def admin_login():
    global token, current_role
    print("\n--- Admin Login ---")
    username = input("Username: ")
    password = input("Password: ")
    res = requests.post(f"{BASE_URL}/mgmt/login", json={"username": username, "password": password})
    data = parse_response(res)
    if data is None:
        return
    if res.status_code == 200:
        token = data["token"]
        current_role = "admin"
        print("✅ Admin login successful!")
    else:
        print(f"❌ Error: {data.get('error')}")

def user_login():
    global token, current_role
    print("\n--- User Login ---")
    username = input("Username: ")
    password = input("Password: ")
    res = requests.post(f"{BASE_URL}/user/login", json={"username": username, "password": password})
    data = parse_response(res)
    if data is None:
        return
    if res.status_code == 200:
        token = data["token"]
        current_role = "user"
        print("✅ User login successful!")
    else:
        print(f"❌ Error: {data.get('error')}")

def create_user():
    if current_role != "admin":
        print("❌ Admin access required!")
        return
    print("\n--- Create User ---")
    username = input("New username: ")
    password = input("New password: ")
    res = requests.post(f"{BASE_URL}/mgmt/create-user",
                       headers=set_headers(),
                       json={"username": username, "password": password})
    data = parse_response(res)
    if data is None:
        return
    if res.status_code == 200:
        print(f"✅ {data.get('message')}")
    else:
        print(f"❌ Error: {data.get('error')}")

def send_message():
    if not token:
        print("❌ Please login first!")
        return
    print("\n--- Chat ---")
    message = input("You: ")
    res = requests.post(f"{BASE_URL}/chat",
                       headers=set_headers(),
                       json={"message": message, "session_id": session_id})
    data = parse_response(res)
    if data is None:
        return
    if res.status_code == 200:
        print(f"Bot: {data.get('response')}")
    else:
        print(f"❌ Error: {data.get('error')}")

def view_history():
    if not token:
        print("❌ Please login first!")
        return
    res = requests.get(f"{BASE_URL}/chat/history?session_id={session_id}",
                      headers=set_headers())
    data = parse_response(res)
    if data is None:
        return
    if res.status_code == 200:
        print(f"\n--- Chat History ({data.get('count')} messages) ---")
        for h in data.get("history", []):
            print(f"You: {h['user_message']}")
            print(f"Bot: {h['assistant_response']}")
            print("---")
    else:
        print(f"❌ Error: {data.get('error')}")

def change_session():
    global session_id
    session_id = input("Enter session ID: ")
    print(f"✅ Session changed to: {session_id}")

def main():
    print("Chatbot Client")
    print(f"Connected to: {BASE_URL}")
    print("========================")
    while True:
        print(f"\nLogged in as: {current_role or 'Not logged in'} | Session: {session_id}")
        print("1. Admin Login")
        print("2. User Login")
        print("3. Create User (Admin only)")
        print("4. Send Message")
        print("5. View History")
        print("6. Change Session")
        print("7. Exit")
        choice = input("\nChoice: ")
        if choice == "1":
            admin_login()
        elif choice == "2":
            user_login()
        elif choice == "3":
            create_user()
        elif choice == "4":
            send_message()
        elif choice == "5":
            view_history()
        elif choice == "6":
            change_session()
        elif choice == "7":
            print("Goodbye!")
            break
        else:
            print("Invalid choice!")

if __name__ == "__main__":
    main()
