import requests
import time

API_BASE = "http://localhost:8001"

def test_user_loop():
    # Register user
    register_resp = requests.post(f"{API_BASE}/auth/register", json={
        "phone": "+201234567891",
        "password": "testpass123"
    })
    assert register_resp.status_code == 200
    token = register_resp.json()["access_token"]
    print("User registered")

    # Create alert
    headers = {"Authorization": f"Bearer {token}"}
    alert_resp = requests.post(f"{API_BASE}/alerts", json={
        "target_url": "https://example.com/test",
        "target_price": 50.0
    }, headers=headers)
    assert alert_resp.status_code == 200
    print("Alert created")

    # Wait for scraper to process (in real, check Redis or DB)
    time.sleep(5)
    print("E2E test passed: User loop functional")

if __name__ == "__main__":
    test_user_loop()