import os
import sys
import requests
from dotenv import load_dotenv

# Load .env
load_dotenv()

url = os.getenv("TELEMETRY_URL")
env = os.getenv("TELEMETRY_ENV")

print(f"DEBUG: Loaded Environment Variables")
print(f"  URL: {url}")
print(f"  ENV: {env}")

if not url:
    print("ERROR: TELEMETRY_URL is not set!")
    sys.exit(1)

if env == 'dev':
    print("WARNING: TELEMETRY_ENV is 'dev'. The real app would NOT send data.")
    print("Sending anyway for this debug test...")

print(f"Attempting to send GET request to {url}...")
try:
    response = requests.get(url, params={"uid": "debug-user", "version": "debug-1.0", "platform": "debug-os"}, timeout=5)
    print(f"Response Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")
    
    if response.status_code == 200:
        print("SUCCESS! The server received the request.")
    else:
        print("FAILURE! The server returned an error.")
        
except Exception as e:
    print(f"EXCEPTION: {e}")
