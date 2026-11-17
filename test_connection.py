import os

import requests
from dotenv import load_dotenv

load_dotenv()

access_key = os.getenv("ONSHAPE_ACCESS_KEY")
secret_key = os.getenv("ONSHAPE_SECRET_KEY")
document_id = os.getenv("ONSHAPE_DOCUMENT_ID")

url = f"https://cad.onshape.com/api/v10/documents/{document_id}"

response = requests.get(
    url,
    auth=(access_key, secret_key)
)

print("Status:", response.status_code)
print("Response:", response.text[:1000])
