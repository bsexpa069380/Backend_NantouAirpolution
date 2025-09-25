import os
import boto3
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=os.getenv("R2_ENDPOINT"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
    region_name="auto"
)

print("✅ Client created OK")

bucket = os.getenv("R2_BUCKET")
base_url = os.getenv("R2_PUBLIC_URL_BASE").rstrip("/")

# Upload test image
with open("sample.jpg", "rb") as f:
    s3.upload_fileobj(f, bucket, "test/sample.jpg")

print("✅ Uploaded sample.jpg")
print("🌍 Public URL:", f"{base_url}/test/sample.jpg")

# Upload test PDF
with open("sample.pdf", "rb") as f:
    s3.upload_fileobj(f, bucket, "test/sample.pdf")

print("✅ Uploaded sample.pdf")
print("🌍 Public URL:", f"{base_url}/test/sample.pdf")
