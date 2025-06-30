"""AWS Lambda function for uploading generated videos to YouTube."""

import json
import logging
import os
import boto3
import tempfile
import time
from typing import Any, Dict, List
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3 = boto3.client("s3", region_name="us-east-2")
dynamodb = boto3.client("dynamodb", region_name="us-east-2")

# Environment variables
S3_BUCKET = os.environ.get("S3_BUCKET")
JOB_COORDINATION_TABLE = os.environ.get("JOB_COORDINATION_TABLE")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Upload composed videos to YouTube."""
    try:
        job_id = event.get("job_id")
        if not job_id:
            raise ValueError("job_id is required")
        
        video_type = event.get("video_type", "regular")
        response_metadata = event.get("response", {})
        
        # Get job details and merge with event metadata
        job_details = get_job_details(job_id)
        if not job_details:
            raise ValueError(f"Job {job_id} not found")
        
        if response_metadata:
            merge_metadata(job_details, response_metadata)
        
        # Download video and upload to YouTube
        video_s3_key = find_video_file(job_id, video_type)
        if not video_s3_key:
            raise ValueError(f"No video found for job {job_id}")
        
        temp_video_path = download_video(video_s3_key)
        try:
            upload_result = upload_to_youtube(temp_video_path, job_details, job_id, video_type)
            update_job_status(job_id, "complete", upload_result.get("video_id"), upload_result.get("video_url"))
            
            return create_response(200, {
                "message": "Video uploaded successfully",
                "job_id": job_id,
                "youtube_video_id": upload_result.get("video_id"),
                "youtube_url": upload_result.get("video_url")
            })
        finally:
            cleanup_temp_file(temp_video_path)
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        job_id = event.get("job_id")
        if job_id:
            update_job_status(job_id, "failed", error=str(e))
        
        return create_response(500, {"error": "Upload failed", "details": str(e)})

def get_job_details(job_id: str) -> Dict[str, Any] | None:
    """Get job details from DynamoDB."""
    if not JOB_COORDINATION_TABLE:
        raise ValueError("JOB_COORDINATION_TABLE not configured")
    
    try:
        response = dynamodb.get_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}}
        )
        
        if "Item" not in response:
            return None
        
        item = response["Item"]
        return {
            "job_id": item.get("job_id", {}).get("S", ""),
            "original_prompt": item.get("original_prompt", {}).get("S", ""),
            "role": item.get("role", {}).get("S", ""),
            "video_type": item.get("video_type", {}).get("S", "regular"),
            "video_title": item.get("video_title", {}).get("S", ""),
            "video_summary": item.get("video_summary", {}).get("S", ""),
            "video_hashtags": item.get("video_hashtags", {}).get("S", ""),
            "video_topic": item.get("video_topic", {}).get("S", "")
        }
        
    except Exception as e:
        logger.error(f"Error getting job details: {str(e)}")
        return None

def merge_metadata(job_details: Dict[str, Any], response_metadata: Dict[str, Any]) -> None:
    """Merge response metadata into job details."""
    mapping = {
        "title": "video_title",
        "video_title": "video_title",
        "summary": "video_summary", 
        "description": "video_summary",
        "hashtags": "video_hashtags",
        "tags": "video_hashtags",
        "topic": "video_topic"
    }
    
    for source_key, target_key in mapping.items():
        if source_key in response_metadata:
            job_details[target_key] = response_metadata[source_key]

def find_video_file(job_id: str, video_type: str) -> str | None:
    """Find video file in S3."""
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET not configured")
    
    prefix = f"generated-videos/{job_id}/" if video_type == "short" else f"composed-videos/{job_id}/"
    
    try:
        response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        
        if "Contents" not in response:
            return None
        
        # Find appropriate video file
        for obj in response["Contents"]:
            key = obj["Key"]
            if key.endswith(".mp4"):
                if video_type == "short" and "scene_01" in key:
                    return key
                elif video_type != "short" and ("final" in key or "composed" in key):
                    return key
        
        # Fallback: return first mp4 file
        for obj in response["Contents"]:
            if obj["Key"].endswith(".mp4"):
                return obj["Key"]
        
        return None
        
    except Exception as e:
        logger.error(f"Error finding video file: {str(e)}")
        return None

def download_video(s3_key: str) -> str:
    """Download video from S3 to temporary file."""
    if not S3_BUCKET:
        raise ValueError("S3_BUCKET not configured")
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", dir="/tmp")
    temp_path = temp_file.name
    temp_file.close()
    
    s3.download_file(S3_BUCKET, s3_key, temp_path)
    
    if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
        raise ValueError(f"Failed to download video: {s3_key}")
    
    return temp_path

def cleanup_temp_file(file_path: str) -> None:
    """Clean up temporary file."""
    if os.path.exists(file_path):
        os.remove(file_path)
        logger.info(f"Cleaned up: {file_path}")

def update_job_status(job_id: str, status: str, video_id: str | None = None, 
                     video_url: str | None = None, error: str | None = None) -> None:
    """Update job status in DynamoDB."""
    if not JOB_COORDINATION_TABLE:
        return
    
    try:
        update_expression = "SET upload_status = :status, upload_updated_at = :timestamp"
        expression_values = {
            ":status": {"S": status},
            ":timestamp": {"N": str(int(time.time()))}
        }
        
        if video_id:
            update_expression += ", youtube_video_id = :video_id"
            expression_values[":video_id"] = {"S": video_id}
        
        if video_url:
            update_expression += ", youtube_url = :video_url"
            expression_values[":video_url"] = {"S": video_url}
        
        if error:
            update_expression += ", upload_error = :error"
            expression_values[":error"] = {"S": error}
        
        dynamodb.update_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
        
    except Exception as e:
        logger.error(f"Error updating job status: {str(e)}")

def create_response(status_code: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create standardized response."""
    return {
        "statusCode": status_code,
        "body": json.dumps(data)
    }

def upload_to_youtube(video_path: str, job_details: Dict[str, Any], job_id: str, video_type: str) -> Dict[str, Any]:
    """Upload video to YouTube."""
    try:
        if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
            raise ValueError("YouTube credentials not configured")
        
        credentials = Credentials(
            token=None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
            scopes=[YOUTUBE_UPLOAD_SCOPE]
        )
        
        youtube = build("youtube", "v3", credentials=credentials)
        title, description, tags = prepare_video_metadata(job_details, job_id, video_type)
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        insert_request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        
        response = None
        retry = 0
        
        while response is None and retry < 3:
            try:
                status, response = insert_request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    retry += 1
                    time.sleep(2 ** retry)
                    continue
                else:
                    raise
        
        if response:
            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            return {"success": True, "video_id": video_id, "video_url": video_url, "title": title}
        else:
            raise ValueError("Upload failed")
            
    except Exception as e:
        logger.error(f"YouTube upload error: {str(e)}")
        raise

def prepare_video_metadata(job_details: Dict[str, Any], job_id: str, video_type: str) -> tuple[str, str, List[str]]:
    """Prepare YouTube metadata."""
    original_prompt = job_details.get("original_prompt", "AI Generated Video")
    role = job_details.get("role", "storyteller")
    
    title = job_details.get("video_title") or f"AI {'Short' if video_type == 'short' else 'Story'}: {original_prompt[:80]}"
    if len(title) > 100:
        title = title[:97] + "..."
    
    summary = job_details.get("video_summary", "")
    description = f"""🤖 AI Generated Video!

{summary if summary else f'Original Prompt: {original_prompt}'}

🎭 Role: {role.title()}
⚡ Generated by LetMeCookAI

Job ID: {job_id}
Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
"""
    
    hashtags = job_details.get("video_hashtags", "")
    if hashtags:
        if isinstance(hashtags, list):
            tags = [tag.replace('#', '').strip() for tag in hashtags if tag.strip()][:10]
        else:
            tags = [tag.replace('#', '').strip() for tag in str(hashtags).split(',') if tag.strip()][:10]
    else:
        tags = ["AI", "AI Generated", "Video Generation", "LetMeCookAI"]
        if video_type == "short":
            tags.extend(["Shorts", "Short Form"])
        else:
            tags.extend(["Story", "Long Form"])
    
    return title, description, tags[:10]


