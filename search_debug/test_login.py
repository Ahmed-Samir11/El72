import requests

BASE = "http://127.0.0.1:8000"

# Register a fresh user
phone = "+201000000999"
password = "TestPass123"

r = requests.post(f"{BASE}/auth/register", json={"phone": phone, "password": password}, timeout=10)
print("register:", r.status_code, r.text[:200])

# Now login with the same credentials
r2 = requests.post(f"{BASE}/auth/login", json={"phone": phone, "password": password}, timeout=10)
print("login:", r2.status_code, r2.text[:200])

# Now login with a WRONG password to confirm 401 path
r3 = requests.post(f"{BASE}/auth/login", json={"phone": phone, "password": "WrongPass999"}, timeout=10)
print("login(wrong):", r3.status_code, r3.text[:200])
