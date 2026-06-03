import asyncio
import aiohttp
import argparse
import time
import statistics
import uuid
from datetime import datetime

BASE_URL = "https://chatbot-linux-taimor.azurewebsites.net/api"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin@123"

async def create_user(session, admin_token, username, password):
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    async with session.post(f"{BASE_URL}/mgmt/create-user",
                           json={"username": username, "password": password},
                           headers=headers) as res:
        return res.status == 200

async def login_user(session, username, password):
    async with session.post(f"{BASE_URL}/user/login",
                           json={"username": username, "password": password}) as res:
        if res.status == 200:
            data = await res.json()
            return data.get("token")
        return None

async def send_message(session, token, session_id, message):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    start = time.time()
    try:
        async with session.post(f"{BASE_URL}/chat",
                               json={"message": message, "session_id": session_id},
                               headers=headers) as res:
            latency = time.time() - start
            success = res.status == 200
            return success, latency
    except Exception:
        return False, time.time() - start

async def simulate_user(session, admin_token, user_num, messages_per_user, delay):
    username = f"loaduser_{user_num}_{uuid.uuid4().hex[:6]}"
    password = "Test@1234"
    session_id = f"session_{uuid.uuid4().hex}"

    results = []
    auth_failures = 0

    created = await create_user(session, admin_token, username, password)
    if not created:
        return results, 1

    await asyncio.sleep(delay * user_num * 0.1)
    token = await login_user(session, username, password)
    if not token:
        auth_failures += 1
        return results, auth_failures

    messages = [
        "Hello! How are you?",
        "What is Python programming?",
        "Tell me about Azure Functions.",
        "What is JWT authentication?",
        "Thank you for your help!"
    ]

    for i in range(messages_per_user):
        msg = messages[i % len(messages)]
        success, latency = await send_message(session, token, session_id, msg)
        results.append((success, latency))
        await asyncio.sleep(delay)

    return results, auth_failures

async def get_admin_token(session):
    async with session.post(f"{BASE_URL}/mgmt/login",
                           json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}) as res:
        if res.status == 200:
            data = await res.json()
            return data.get("token")
        return None

async def run_load_test(num_users, messages_per_user, delay):
    print(f"\n🚀 Starting Load Test")
    print(f"====================")
    print(f"Users: {num_users}")
    print(f"Messages per user: {messages_per_user}")
    print(f"Delay: {delay}s")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"====================\n")

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        print("🔑 Getting admin token...")
        admin_token = await get_admin_token(session)
        if not admin_token:
            print("❌ Admin login failed! Check BASE_URL and credentials.")
            return

        print(f"✅ Admin token received!")
        print(f"👥 Creating {num_users} users and running chat...\n")

        tasks = [
            simulate_user(session, admin_token, i, messages_per_user, delay)
            for i in range(num_users)
        ]
        all_results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    all_latencies = []
    total_success = 0
    total_failed = 0
    total_auth_failures = 0

    for results, auth_fail in all_results:
        total_auth_failures += auth_fail
        for success, latency in results:
            all_latencies.append(latency)
            if success:
                total_success += 1
            else:
                total_failed += 1

    total_requests = total_success + total_failed

    print("\n📊 LOAD TEST REPORT")
    print("===================")
    print(f"Total users:          {num_users}")
    print(f"Messages per user:    {messages_per_user}")
    print(f"Total requests:       {total_requests}")
    print(f"Successful requests:  {total_success}")
    print(f"Failed requests:      {total_failed}")
    print(f"Authentication failures: {total_auth_failures}")

    if all_latencies:
        sorted_lat = sorted(all_latencies)
        avg = statistics.mean(all_latencies)
        p50 = sorted_lat[int(len(sorted_lat) * 0.50)]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]
        error_rate = (total_failed / total_requests * 100) if total_requests > 0 else 0

        print(f"Average latency:      {avg:.2f}s")
        print(f"P50 latency:          {p50:.2f}s")
        print(f"P95 latency:          {p95:.2f}s")
        print(f"P99 latency:          {p99:.2f}s")
        print(f"Error rate:           {error_rate:.1f}%")

    print(f"Total test time:      {total_time:.2f}s")
    print("===================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chatbot Load Test")
    parser.add_argument("--users", type=int, default=10, help="Number of users")
    parser.add_argument("--messages-per-user", type=int, default=3, help="Messages per user")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between messages")
    parser.add_argument("--url", type=str, default="https://chatbot-linux-taimor.azurewebsites.net/api", help="Base URL")
    args = parser.parse_args()

    BASE_URL = args.url
    asyncio.run(run_load_test(args.users, args.messages_per_user, args.delay))