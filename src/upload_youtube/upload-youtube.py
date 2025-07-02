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

# Log environment variables at module load time
logger.info("=== MODULE LOADED - CHECKING ENVIRONMENT VARIABLES ===")
logger.info(f"S3_BUCKET: {'SET' if S3_BUCKET else 'NOT SET'}")
logger.info(f"JOB_COORDINATION_TABLE: {'SET' if JOB_COORDINATION_TABLE else 'NOT SET'}")
logger.info(f"YOUTUBE_CLIENT_ID: {'SET' if YOUTUBE_CLIENT_ID else 'NOT SET'}")
logger.info(f"YOUTUBE_CLIENT_SECRET: {'SET' if YOUTUBE_CLIENT_SECRET else 'NOT SET'}")
logger.info(f"YOUTUBE_REFRESH_TOKEN: {'SET' if YOUTUBE_REFRESH_TOKEN else 'NOT SET'}")
if YOUTUBE_CLIENT_ID:
    logger.info(f"Client ID prefix: {YOUTUBE_CLIENT_ID[:15]}...")
if YOUTUBE_REFRESH_TOKEN:
    logger.info(f"Refresh token length: {len(YOUTUBE_REFRESH_TOKEN)} chars")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Upload composed videos to YouTube."""
    logger.info("=== LAMBDA HANDLER STARTED ===")
    logger.info(f"Event: {json.dumps(event, indent=2)}")
    
    try:
        job_id = event.get("job_id")
        logger.info(f"Job ID: {job_id}")
        if not job_id:
            raise ValueError("job_id is required")
        
        video_type = event.get("video_type", "regular")
        response_metadata = event.get("response", {})
        logger.info(f"Video type: {video_type}")
        logger.info(f"Response metadata keys: {list(response_metadata.keys()) if response_metadata else 'None'}")
        
        # Get job details and merge with event metadata
        logger.info("Getting job details from DynamoDB...")
        job_details = get_job_details(job_id)
        if not job_details:
            raise ValueError(f"Job {job_id} not found")
        logger.info("Job details retrieved successfully")
        
        if response_metadata:
            logger.info("Merging response metadata...")
            merge_metadata(job_details, response_metadata)
        
        # Download video and upload to YouTube
        logger.info("Finding video file in S3...")
        video_s3_key = find_video_file(job_id, video_type)
        if not video_s3_key:
            raise ValueError(f"No video found for job {job_id}")
        logger.info(f"Found video file: {video_s3_key}")
        
        logger.info("Downloading video from S3...")
        temp_video_path = download_video(video_s3_key)
        logger.info(f"Video downloaded to: {temp_video_path}")
        
        try:
            logger.info("=== CALLING UPLOAD_TO_YOUTUBE FUNCTION ===")
            upload_result = upload_to_youtube(temp_video_path, job_details, job_id, video_type)
            logger.info("=== UPLOAD_TO_YOUTUBE COMPLETED SUCCESSFULLY ===")
            update_job_status(job_id, "complete", upload_result.get("video_id"), upload_result.get("video_url"))
            
            return create_response(200, {
                "message": "Video uploaded successfully",
                "job_id": job_id,
                "youtube_video_id": upload_result.get("video_id"),
                "youtube_url": upload_result.get("video_url")
            })
        except Exception as upload_error:
            logger.error(f"=== UPLOAD_TO_YOUTUBE FAILED ===")
            logger.error(f"Upload function error: {str(upload_error)}")
            logger.error(f"Upload function error type: {type(upload_error).__name__}")
            raise
        finally:
            cleanup_temp_file(temp_video_path)
        
    except Exception as e:
        logger.error(f"=== LAMBDA HANDLER ERROR ===")
        logger.error(f"Upload error: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
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
    logger.info(f"=== STARTING YOUTUBE UPLOAD FOR JOB {job_id} ===")
    logger.info(f"Video path: {video_path}")
    logger.info(f"Video type: {video_type}")
    
    # Check credentials first - outside try block
    logger.info("Checking YouTube credentials...")
    logger.error(f"CLIENT_ID present: {bool(YOUTUBE_CLIENT_ID)}")
    logger.error(f"CLIENT_SECRET present: {bool(YOUTUBE_CLIENT_SECRET)}")
    logger.error(f"REFRESH_TOKEN present: {bool(YOUTUBE_REFRESH_TOKEN)}")
    
    if not all([YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN]):
        logger.error("YouTube credentials missing - check environment variables")
        raise ValueError("YouTube credentials not configured")
    
    logger.info(f"Using Client ID: {YOUTUBE_CLIENT_ID[:20] if YOUTUBE_CLIENT_ID else 'None'}...")
    logger.info(f"Client Secret length: {len(YOUTUBE_CLIENT_SECRET) if YOUTUBE_CLIENT_SECRET else 0} chars")
    logger.info(f"Refresh Token length: {len(YOUTUBE_REFRESH_TOKEN) if YOUTUBE_REFRESH_TOKEN else 0} chars")
    
    try:
        
        logger.info("STEP 1: Creating OAuth2 Credentials object...")
        try:
            credentials = Credentials(
                token=None,
                refresh_token=YOUTUBE_REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=YOUTUBE_CLIENT_ID,
                client_secret=YOUTUBE_CLIENT_SECRET,
                scopes=[YOUTUBE_UPLOAD_SCOPE]
            )
            logger.info("STEP 1: OAuth2 Credentials object created successfully")
        except Exception as cred_error:
            logger.error(f"STEP 1 FAILED: Failed to create credentials object: {str(cred_error)}")
            logger.error(f"Credential error type: {type(cred_error).__name__}")
            raise
        
        # Log credential info (without sensitive data)
        logger.info(f"Credentials created - Client ID: {YOUTUBE_CLIENT_ID[:10] if YOUTUBE_CLIENT_ID else 'None'}...")
        logger.info(f"Token URI: {credentials.token_uri}")
        logger.info(f"Scopes: {credentials.scopes}")
        
        logger.info("STEP 2: Building YouTube API client (this triggers token refresh)...")
        try:
            youtube = build("youtube", "v3", credentials=credentials)
            logger.info("STEP 2: YouTube API client built successfully")
        except HttpError as http_error:
            logger.error(f"STEP 2 FAILED: HTTP Error building YouTube client: {str(http_error)}")
            logger.error(f"HTTP Status: {http_error.resp.status}")
            logger.error(f"HTTP Reason: {http_error.resp.reason}")
            logger.error(f"Error Content: {http_error.content}")
            
            # Decode error content if it's bytes
            if hasattr(http_error, 'content') and http_error.content:
                try:
                    error_content = http_error.content.decode('utf-8') if isinstance(http_error.content, bytes) else str(http_error.content)
                    logger.error(f"Decoded Error Content: {error_content}")
                except:
                    logger.error("Could not decode error content")
            raise
        except Exception as auth_error:
            logger.error(f"STEP 2 FAILED: Failed to build YouTube client: {str(auth_error)}")
            logger.error(f"Auth error type: {type(auth_error).__name__}")
            
            # Check if this is an OAuth2 unauthorized_client error
            error_str = str(auth_error).lower()
            if 'unauthorized_client' in error_str:
                logger.error("UNAUTHORIZED_CLIENT ERROR DETECTED!")
                logger.error("This error occurs when:")
                logger.error("1. Client ID doesn't match the one in Google Cloud Console")
                logger.error("2. Client Secret doesn't match the one in Google Cloud Console") 
                logger.error("3. The OAuth2 application type is incorrect (should be 'Desktop application')")
                logger.error("4. The refresh token was generated with different client credentials")
                logger.error(f"Current Client ID (partial): {YOUTUBE_CLIENT_ID[:20] if YOUTUBE_CLIENT_ID else 'None'}...")
                logger.error("ACTION REQUIRED: Verify your Google Cloud Console OAuth2 credentials match exactly")
            
            if 'refresh' in error_str or 'token' in error_str:
                logger.error("This appears to be a token refresh error")
                logger.error("The refresh token may have been revoked or expired")
                logger.error("You may need to regenerate the refresh token")
            
            raise
        
        logger.info("STEP 3: Preparing video metadata...")
        title, description, tags = prepare_video_metadata(job_details, job_id, video_type)
        logger.info(f"Prepared metadata - Title: {title[:50]}...")
        logger.info(f"Description length: {len(description)} chars")
        logger.info(f"Tags: {tags}")
        
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
        
        logger.info(f"Creating media upload for file: {video_path}")
        logger.info(f"File size: {os.path.getsize(video_path) / (1024*1024):.2f} MB")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        
        logger.info("Starting YouTube upload request...")
        insert_request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=media)
        
        response = None
        retry = 0
        
        while response is None and retry < 3:
            try:
                logger.info(f"Upload attempt {retry + 1}/3")
                status, response = insert_request.next_chunk()
                if status:
                    logger.info(f"Upload progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                logger.error(f"HttpError during upload: {str(e)}")
                logger.error(f"HTTP Status: {e.resp.status}")
                logger.error(f"HTTP Reason: {e.resp.reason}")
                
                if hasattr(e, 'content') and e.content:
                    logger.error(f"Error Content: {e.content}")
                
                if e.resp.status in [500, 502, 503, 504]:
                    retry += 1
                    if retry < 3:
                        wait_time = 2 ** retry
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error("Max retries reached for server errors")
                        raise
                elif e.resp.status == 401:
                    logger.error("Unauthorized error - check your YouTube API credentials")
                    logger.error("This could mean:")
                    logger.error("1. Invalid client ID or client secret")
                    logger.error("2. Expired or invalid refresh token")
                    logger.error("3. API not enabled for this project")
                    logger.error("4. Quota exceeded")
                    raise
                elif e.resp.status == 403:
                    logger.error("Forbidden error - check API permissions and quota")
                    logger.error("This could mean:")
                    logger.error("1. YouTube API not enabled")
                    logger.error("2. Insufficient permissions")
                    logger.error("3. Quota exceeded")
                    raise
                else:
                    logger.error(f"Non-retryable HTTP error: {e.resp.status}")
                    raise
            except Exception as upload_error:
                logger.error(f"Unexpected error during upload: {str(upload_error)}")
                logger.error(f"Error type: {type(upload_error).__name__}")
                raise
        
        if response:
            video_id = response["id"]
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            logger.info(f"Upload successful! Video ID: {video_id}")
            logger.info(f"Video URL: {video_url}")
            logger.info(f"Video title: {title}")
            return {"success": True, "video_id": video_id, "video_url": video_url, "title": title}
        else:
            logger.error("Upload failed - no response received after retries")
            raise ValueError("Upload failed")
            
    except Exception as e:
        logger.error(f"YouTube upload error: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Job ID: {job_id}, Video type: {video_type}")
        logger.error(f"Video path: {video_path}")
        raise

def prepare_video_metadata(job_details: Dict[str, Any], job_id: str, video_type: str) -> tuple[str, str, List[str]]:
    """Prepare YouTube metadata."""
    original_prompt = job_details.get("original_prompt", "AI Generated Video")
    role = job_details.get("role", "storyteller")
    
    title = job_details.get("video_title") or f"AI {'Short' if video_type == 'short' else 'Story'}: {original_prompt[:80]}"
    if len(title) > 100:
        title = title[:97] + "..."
    
    summary = job_details.get("video_summary", "")
    
    # Build scene voiceovers
    scenes = job_details.get("scenes", [])
    scene_voiceovers = "\n".join([s.get("voiceover", "") for s in scenes if isinstance(s, dict) and s.get("voiceover")])
    
    # Build hashtags
    hashtags = job_details.get("video_hashtags", [])
    if isinstance(hashtags, list):
        hashtag_text = "\n".join([hashtag for hashtag in hashtags if hashtag.strip()])
    else:
        hashtag_text = str(hashtags) if hashtags else ""
    
    description = f"""
{summary}

{scene_voiceovers}

{hashtag_text}
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


