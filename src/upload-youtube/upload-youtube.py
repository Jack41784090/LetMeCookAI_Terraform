"""
AWS Lambda function for uploading generated videos to YouTube.
This function is triggered after video composition is complete.
"""

import json
import logging
import os
import boto3
import requests
from typing import Any, Dict, List
import tempfile
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import time

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client("s3", region_name="us-east-2")
dynamodb = boto3.client("dynamodb", region_name="us-east-2")
ssm = boto3.client("ssm", region_name="us-east-2")

# Environment variables
S3_BUCKET = os.environ.get("S3_BUCKET")
JOB_COORDINATION_TABLE = os.environ.get("JOB_COORDINATION_TABLE")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

# YouTube API scopes
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to upload composed videos to YouTube.
    
    Args:
        event: Contains job_id and video information
        context: Lambda context object
    
    Returns:
        Response indicating upload status
    """
    try:
        logger.info(f"Received upload event: {json.dumps(event, default=str)}")
        
        # Extract job information
        job_id = event.get("job_id")
        video_type = event.get("video_type", "regular")
        
        if not job_id:
            raise ValueError("job_id is required")
        
        # Get job details from DynamoDB
        job_details = get_job_details(job_id)
        if not job_details:
            raise ValueError(f"Job {job_id} not found in coordination table")
        
        # Get video file from S3
        video_s3_key = get_composed_video_s3_key(job_id, video_type)
        if not video_s3_key:
            raise ValueError(f"No composed video found for job {job_id}")
        
        # Download video to temporary file
        temp_video_path = download_video_from_s3(video_s3_key)
        
        try:
            # Upload to YouTube
            upload_result = upload_to_youtube(
                temp_video_path, 
                job_details, 
                job_id, 
                video_type
            )
            
            # Update job coordination status
            if upload_result.get("video_id") and upload_result.get("video_url"):
                update_job_upload_status(
                    job_id, 
                    "complete", 
                    upload_result.get("video_id"), 
                    upload_result.get("video_url")
                )
            
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Video uploaded successfully to YouTube",
                    "job_id": job_id,
                    "youtube_video_id": upload_result.get("video_id"),
                    "youtube_url": upload_result.get("video_url")
                })
            }
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_video_path):
                os.remove(temp_video_path)
                logger.info(f"Cleaned up temporary file: {temp_video_path}")
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        
        # Update job coordination status to failed
        job_id_value = event.get("job_id") if 'event' in locals() else None
        if job_id_value:
            try:
                update_job_upload_status(job_id_value, "failed", error=str(e))
            except:
                pass
        
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Upload failed",
                "details": str(e)
            })
        }


def get_job_details(job_id: str) -> Dict[str, Any] | None:
    """Get job details from DynamoDB coordination table."""
    try:
        if not JOB_COORDINATION_TABLE:
            raise ValueError("JOB_COORDINATION_TABLE environment variable not set")
        
        response = dynamodb.get_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}}
        )
        
        if "Item" not in response:
            return None
        
        item = response["Item"]
        
        # Convert DynamoDB item to regular dict
        job_details = {
            "job_id": item.get("job_id", {}).get("S", ""),
            "original_prompt": item.get("original_prompt", {}).get("S", ""),
            "role": item.get("role", {}).get("S", ""),
            "video_type": item.get("video_type", {}).get("S", "regular"),
            "created_at": int(item.get("created_at", {}).get("N", "0")),
            "composition_status": item.get("composition_status", {}).get("S", ""),
            "video_audio_status": item.get("video_audio_status", {}).get("S", "")
        }
        
        logger.info(f"Retrieved job details for {job_id}: {job_details}")
        return job_details
        
    except Exception as e:
        logger.error(f"Error getting job details: {str(e)}")
        return None


def get_composed_video_s3_key(job_id: str, video_type: str) -> str | None:
    """Get the S3 key for the composed video."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")
        
        if video_type == "short":
            # For shorts, look for the original video files
            prefix = f"generated-videos/{job_id}/"
        else:
            # For regular videos, look for composed video
            prefix = f"composed-videos/{job_id}/"
        
        response = s3.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix
        )
        
        if "Contents" not in response:
            logger.warning(f"No objects found with prefix: {prefix}")
            return None
        
        # Find the main video file
        for obj in response["Contents"]:
            key = obj["Key"]
            if video_type == "short":
                # For shorts, find the first scene video
                if key.endswith(".mp4") and "scene_01" in key:
                    logger.info(f"Found short video: {key}")
                    return key
            else:
                # For regular videos, find the final composed video
                if key.endswith(".mp4") and ("final" in key or "composed" in key):
                    logger.info(f"Found composed video: {key}")
                    return key
        
        # Fallback: return the first mp4 file found
        for obj in response["Contents"]:
            if obj["Key"].endswith(".mp4"):
                logger.info(f"Fallback: Using video file: {obj['Key']}")
                return obj["Key"]
        
        logger.warning(f"No video files found for job {job_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error finding composed video: {str(e)}")
        return None


def download_video_from_s3(s3_key: str) -> str:
    """Download video from S3 to a temporary file."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(
            delete=False, 
            suffix=".mp4", 
            dir="/tmp"
        )
        temp_path = temp_file.name
        temp_file.close()
        
        logger.info(f"Downloading {s3_key} to {temp_path}")
        
        s3.download_file(S3_BUCKET, s3_key, temp_path)
        
        # Verify file was downloaded
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise ValueError(f"Failed to download video file from S3: {s3_key}")
        
        file_size = os.path.getsize(temp_path)
        logger.info(f"Successfully downloaded video: {temp_path} ({file_size} bytes)")
        
        return temp_path
        
    except Exception as e:
        logger.error(f"Error downloading video from S3: {str(e)}")
        raise


def upload_to_youtube(
    video_path: str, 
    job_details: Dict[str, Any], 
    job_id: str, 
    video_type: str
) -> Dict[str, Any]:
    """Upload video to YouTube using the YouTube Data API."""
    try:
        # Validate credentials
        if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
            raise ValueError("YouTube credentials not properly configured")
        
        # Create credentials object
        credentials = Credentials(
            token=None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
            scopes=[YOUTUBE_UPLOAD_SCOPE]
        )
        
        # Build YouTube service
        youtube = build("youtube", "v3", credentials=credentials)
        
        # Prepare video metadata
        title, description, tags = prepare_video_metadata(job_details, job_id, video_type)
        
        # Video upload parameters
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22"  # People & Blogs category
            },
            "status": {
                "privacyStatus": "public",  # or "private", "unlisted"
                "selfDeclaredMadeForKids": False
            }
        }
        
        # Create media upload object
        media = MediaFileUpload(
            video_path,
            chunksize=-1,  # Upload in a single request
            resumable=True,
            mimetype="video/mp4"
        )
        
        logger.info(f"Starting YouTube upload for job {job_id}")
        
        # Execute the upload
        insert_request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        error = None
        retry = 0
        
        while response is None:
            try:
                status, response = insert_request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    # Retry on server errors
                    if retry < 3:
                        retry += 1
                        logger.warning(f"Server error {e.resp.status}, retrying ({retry}/3)")
                        time.sleep(2 ** retry)
                        continue
                    else:
                        raise
                else:
                    raise
        
        if response is not None:
            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            logger.info(f"Successfully uploaded video to YouTube: {video_url}")
            
            return {
                "success": True,
                "video_id": video_id,
                "video_url": video_url,
                "title": title
            }
        else:
            raise ValueError("Upload failed - no response received")
            
    except Exception as e:
        logger.error(f"Error uploading to YouTube: {str(e)}")
        raise


def prepare_video_metadata(
    job_details: Dict[str, Any], 
    job_id: str, 
    video_type: str
) -> tuple[str, str, List[str]]:
    """Prepare title, description, and tags for YouTube video."""
    
    original_prompt = job_details.get("original_prompt", "AI Generated Video")
    role = job_details.get("role", "storyteller")
    
    # Generate title
    if video_type == "short":
        title = f"AI Short: {original_prompt[:80]}..."
    else:
        title = f"AI Story: {original_prompt[:80]}..."
    
    if len(title) > 100:
        title = title[:97] + "..."
    
    # Generate description
    description = f"""🤖 This video was generated using AI technology!

📝 Original Prompt: {original_prompt}

🎭 Narrator Role: {role.title()}

🎬 Video Type: {'Short Form Content' if video_type == 'short' else 'Full Length Story'}

⚡ Generated by LetMeCookAI - An automated video creation system

#AI #AIGenerated #ArtificialIntelligence #VideoGeneration #AutomatedContent #TechDemo
#{"Shorts" if video_type == "short" else "Story"} #Innovation #FutureOfContent

Job ID: {job_id}
Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
"""

    # Generate tags
    tags = [
        "AI",
        "AI Generated",
        "Artificial Intelligence",
        "Video Generation",
        "Automated Content",
        "Tech Demo",
        "Innovation",
        "Future of Content",
        "LetMeCookAI"
    ]
    
    if video_type == "short":
        tags.extend(["Shorts", "Short Form", "Quick Content"])
    else:
        tags.extend(["Story", "Narrative", "Long Form"])
    
    # Add role-based tags
    if role:
        tags.append(role.title())
    
    # Limit tags to YouTube's maximum
    tags = tags[:10]
    
    return title, description, tags


def update_job_upload_status(
    job_id: str, 
    status: str, 
    video_id: str | None = None, 
    video_url: str | None = None, 
    error: str | None = None
) -> None:
    """Update job coordination with upload status."""
    try:
        if not JOB_COORDINATION_TABLE:
            logger.warning("No coordination table specified")
            return
        
        # Prepare update expression and values
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
        
        # Update TTL
        expires_at = int(time.time()) + (30 * 24 * 60 * 60)  # 30 days
        update_expression += ", expires_at = :expires"
        expression_values[":expires"] = {"N": str(expires_at)}
        
        dynamodb.update_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}},
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values
        )
        
        logger.info(f"Updated upload status = {status} for job {job_id}")
        
    except Exception as e:
        logger.error(f"Error updating upload status: {str(e)}")
