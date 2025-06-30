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
        
        # Extract response object from event payload (preferred) or fallback to DynamoDB
        response_from_event = event.get("response", {})
        
        if not job_id:
            raise ValueError("job_id is required")
        
        # Get job details from DynamoDB
        job_details = get_job_details(job_id)
        if not job_details:
            raise ValueError(f"Job {job_id} not found in coordination table")
        
        # Override DynamoDB metadata with event response if present (prioritize event data)
        if response_from_event:
            logger.info(f"Using response object from event payload for job {job_id}")
            # Map response properties to job_details keys for compatibility
            if "title" in response_from_event:
                job_details["video_title"] = response_from_event["title"]
            elif "video_title" in response_from_event:
                job_details["video_title"] = response_from_event["video_title"]
            
            if "summary" in response_from_event:
                job_details["video_summary"] = response_from_event["summary"]
            elif "description" in response_from_event:
                job_details["video_summary"] = response_from_event["description"]
            
            if "hashtags" in response_from_event:
                job_details["video_hashtags"] = response_from_event["hashtags"]
            elif "tags" in response_from_event:
                job_details["video_hashtags"] = response_from_event["tags"]
            
            if "topic" in response_from_event:
                job_details["video_topic"] = response_from_event["topic"]
        else:
            logger.info(f"Using video metadata from DynamoDB for job {job_id}")
        
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
            "video_audio_status": item.get("video_audio_status", {}).get("S", ""),
            # Video metadata fields (from DynamoDB storage)
            "video_title": item.get("video_title", {}).get("S", ""),
            "video_summary": item.get("video_summary", {}).get("S", ""),
            "video_hashtags": item.get("video_hashtags", {}).get("S", ""),
            "video_topic": item.get("video_topic", {}).get("S", "")
        }
        
        # Also try to extract metadata from ai_response if stored in DynamoDB
        ai_response = item.get("ai_response", {}).get("S", "")
        if ai_response:
            try:
                extracted_metadata = extract_metadata_from_ai_response(ai_response)
                # Only use extracted metadata if the direct fields are empty
                for key, value in extracted_metadata.items():
                    if not job_details.get(key) and value:
                        job_details[key] = value
                        logger.info(f"Extracted {key} from ai_response for job {job_id}")
            except Exception as e:
                logger.warning(f"Failed to extract metadata from ai_response for job {job_id}: {str(e)}")
        
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
    """Prepare title, description, and tags for YouTube video using stored metadata."""
    
    original_prompt = job_details.get("original_prompt", "AI Generated Video")
    role = job_details.get("role", "storyteller")
    
    # Use stored video metadata if available (supporting both original and translated field names)
    stored_title = job_details.get("video_title", "") or job_details.get("title", "")
    stored_summary = job_details.get("video_summary", "") or job_details.get("summary", "")
    stored_hashtags = job_details.get("video_hashtags", "") or job_details.get("hashtags", "")
    stored_topic = job_details.get("video_topic", "") or job_details.get("topic", "")
    
    # Generate title - prefer stored title, fallback to generated
    if stored_title:
        title = stored_title
    else:
        if video_type == "short":
            title = f"AI Short: {original_prompt[:80]}..."
        else:
            title = f"AI Story: {original_prompt[:80]}..."
    
    # Ensure title doesn't exceed YouTube's limit
    if len(title) > 100:
        title = title[:97] + "..."
    
    # Generate description - use stored summary if available
    if stored_summary:
        description = f"""🤖 This video was generated using AI technology!

{stored_summary}

🎭 Narrator Role: {role.title()}
🎬 Video Type: {'Short Form Content' if video_type == 'short' else 'Full Length Story'}

⚡ Generated by LetMeCookAI - An automated video creation system

{format_hashtags_for_description(stored_hashtags) if stored_hashtags else '#AI #AIGenerated #ArtificialIntelligence #VideoGeneration #AutomatedContent #TechDemo'}

Job ID: {job_id}
Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
"""
    else:
        # Fallback to original description format
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

    # Generate tags - prefer stored hashtags, fallback to generated
    if stored_hashtags:
        # Handle both list (from event) and string (from DynamoDB) formats
        if isinstance(stored_hashtags, list):
            # From event payload - list of hashtags
            tags = []
            for tag in stored_hashtags:
                tag = str(tag).strip()
                if tag.startswith('#'):
                    tag = tag[1:]  # Remove # symbol for YouTube tags
                if tag and len(tag) <= 50:  # YouTube tag length limit
                    tags.append(tag)
        else:
            # From DynamoDB - comma-separated string
            tags = []
            for tag in str(stored_hashtags).split(','):
                tag = tag.strip()
                if tag.startswith('#'):
                    tag = tag[1:]  # Remove # symbol for YouTube tags
                if tag and len(tag) <= 50:  # YouTube tag length limit
                    tags.append(tag)
        
        # Limit to YouTube's maximum
        tags = tags[:10]
    else:
        # Fallback to default tags
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
    
    logger.info(f"Prepared video metadata - Title: {title[:50]}..., Tags: {len(tags)} tags")
    
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


def format_hashtags_for_description(hashtags) -> str:
    """Format hashtags for YouTube description, handling both list and string formats."""
    if isinstance(hashtags, list):
        # From event payload - list of hashtags
        return ' '.join(hashtags)
    else:
        # From DynamoDB - comma-separated string
        return hashtags.replace(',', ' ')


def extract_metadata_from_ai_response(ai_response: str | Dict[str, Any]) -> Dict[str, str]:
    """Extract video metadata from the nested AI response structure."""
    try:
        # Handle both string and already parsed responses
        if isinstance(ai_response, str):
            response_data = json.loads(ai_response)
        else:
            response_data = ai_response
        
        # Check if response has nested structure (like churning-of-the-ocean.json)
        if "response" in response_data and isinstance(response_data["response"], dict):
            response_obj = response_data["response"]
        else:
            # Direct structure
            response_obj = response_data
        
        metadata = {}
        
        if "title" in response_obj:
            metadata["video_title"] = response_obj["title"]
        
        if "summary" in response_obj:
            metadata["video_summary"] = response_obj["summary"]
        
        if "hashtags" in response_obj:
            hashtags = response_obj["hashtags"]
            if isinstance(hashtags, list):
                # Convert list to comma-separated string for consistency with DynamoDB format
                metadata["video_hashtags"] = ",".join(hashtags)
            else:
                metadata["video_hashtags"] = str(hashtags)
        
        if "topic" in response_obj:
            metadata["video_topic"] = response_obj["topic"]
        
        logger.info(f"Extracted metadata from AI response: {metadata}")
        return metadata
        
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse AI response for metadata extraction: {str(e)}")
        return {}
