import requests
import json
from pathlib import Path

session = requests.Session()
base_url = "http://localhost:5000"

print("=== FLASK API SMOKE TEST ===\n")

endpoints = [
    "/",
    "/admin/pairs",
    "/api/profile",
    "/api/ranking",
]

print("1. GET ENDPOINTS:")
get_results = {}
for endpoint in endpoints:
    try:
        resp = session.get(f"{base_url}{endpoint}", timeout=10)
        get_results[endpoint] = resp.status_code
        status = "OK" if resp.status_code == 200 else f"FAIL ({resp.status_code})"
        print(f"   {endpoint:50} {status}")
    except Exception as e:
        get_results[endpoint] = "ERROR"
        print(f"   {endpoint:50} ERROR: {str(e)}")

print("\n2. FLASK STATUS CHECK:")
try:
    final_resp = session.get(f"{base_url}/", timeout=10)
    final_status = "OK (200)" if final_resp.status_code == 200 else f"FAIL ({final_resp.status_code})"
    print(f"   GET /: {final_status}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n=== SUMMARY ===")
get_ok = sum(1 for v in get_results.values() if v == 200)
print(f"GET Endpoints: {get_ok}/{len(endpoints)} OK")
