import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import boto3
from botocore.exceptions import ClientError

def r2_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('R2_ENDPOINT'),
        aws_access_key_id=os.getenv('R2_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('R2_SECRET_KEY'),
        region_name='auto'
    )

def r2_upload_file(file, folder="articles"):
    try:
        filename = f"article_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        key = f"{folder}/{filename}" if folder else filename
        r2_client().upload_fileobj(
            file,
            os.getenv("R2_BUCKET"),
            key,
            ExtraArgs={"ACL": "public-read"}
        )
        return f"{os.getenv('R2_PUBLIC_URL_BASE').rstrip('/')}/{key}"
    except ClientError as e:
        print(f"R2 upload error: {e}")
        return None

def r2_delete_file(file_url):
    if not file_url or not file_url.startswith("http"):
        return
    try:
        public_base = os.getenv("R2_PUBLIC_URL_BASE").rstrip("/")
        key = file_url.replace(public_base + "/", "")
        s3 = r2_client()
        s3.delete_object(Bucket=os.getenv("R2_BUCKET"), Key=key)
        try:
            s3.head_object(Bucket=os.getenv("R2_BUCKET"), Key=key)
            print(f"[R2 delete warning] Object still exists: {key}")
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                print(f"[R2 delete success] Object deleted: {key}")
            else:
                print(f"[R2 delete head error] {e}")
    except ClientError as e:
        print(f"[R2 delete error] {e}")
