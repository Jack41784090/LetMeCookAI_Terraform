import json
import os
import boto3
import logging
import time
import tempfile
import subprocess
from typing import Any, Dict, List
import requests
from urllib.parse import urlparse

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client("s3", region_name="us-east-2")
dynamodb = boto3.client("dynamodb", region_name="us-east-2")
lambda_client = boto3.client("lambda", region_name="us-east-2")

# Environment variables
S3_BUCKET = os.environ.get("S3_BUCKET")
JOB_COORDINATION_TABLE = os.environ.get("JOB_COORDINATION_TABLE")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to compose audio and video when both are ready.

    Args:
        event: Event containing job_id
        context: Lambda context object

    Returns:
        Response indicating processing status
    """
    try:
        # Log environment info for debugging
        logger.info(f"S3_BUCKET: {S3_BUCKET}")
        logger.info(f"JOB_COORDINATION_TABLE: {JOB_COORDINATION_TABLE}")
        logger.info(f"Event received: {event}")

        job_id = event.get("job_id")
        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "job_id is required"}),
            }

        logger.info(f"Starting composition for job: {job_id}")

        # Check if both audio and video are complete
        if not check_both_ready(job_id):
            logger.info(f"Job {job_id} not ready for composition yet")
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Waiting for completion"}),
            }

        # Update status to composing
        update_job_coordination_status(job_id, "composition_status", "in_progress")

        # Download and compose media
        composed_video_url = compose_media(job_id)

        # Update final status
        update_job_coordination_status(job_id, "composition_status", "complete")
        update_job_coordination_status(job_id, "final_video_url", composed_video_url)

        logger.info(
            f"Successfully composed video for job {job_id}: {composed_video_url}"
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": f"Successfully composed video for job {job_id}",
                    "video_url": composed_video_url,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error in composition: {str(e)}")
        if "job_id" in locals():
            update_job_coordination_status(
                locals()["job_id"], "composition_status", "failed"
            )

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Composition failed", "details": str(e)}),
        }


def check_both_ready(job_id: str) -> bool:
    """Check if both audio and video generation are complete"""
    try:
        response = dynamodb.get_item(
            TableName=JOB_COORDINATION_TABLE, Key={"job_id": {"S": job_id}}
        )

        # Check if item exists
        if "Item" not in response:
            logger.warning(
                f"Job {job_id} not found in DynamoDB table {JOB_COORDINATION_TABLE}"
            )
            return False

        item = response.get("Item", {})
        logger.info(f"Job {job_id} DynamoDB item: {item}")

        # Check for the combined video_audio_status field used by request_media_generation
        video_audio_status = item.get("video_audio_status", {}).get("S", "")

        logger.info(f"Job {job_id} video_audio_status: '{video_audio_status}'")

        return video_audio_status == "complete"

    except Exception as e:
        logger.error(f"Error checking job status: {str(e)}")
        return False


def update_job_coordination_status(job_id: str, field: str, value: str):
    """Update job coordination status in DynamoDB"""
    try:
        # Set TTL for 7 days from now
        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        dynamodb.update_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}},
            UpdateExpression=f"SET {field} = :value, expires_at = :expires",
            ExpressionAttributeValues={
                ":value": {"S": value},
                ":expires": {"N": str(expires_at)},
            },
        )
        logger.info(f"Updated {field} = {value} for job {job_id}")

    except Exception as e:
        logger.error(f"Error updating job status: {str(e)}")


def compose_media(job_id: str) -> str:
    """Download audio and video files, compose them, and upload result"""
    try:
        # Download audio and video files
        audio_files = download_media_files(job_id, "generated-audio")
        video_files = download_media_files(job_id, "generated-videos")

        if not audio_files or not video_files:
            raise ValueError("Missing audio or video files")

        # Sort files by scene number
        audio_files.sort(key=lambda x: x["scene_number"])
        video_files.sort(key=lambda x: x["scene_number"])

        logger.info(
            f"Found {len(audio_files)} audio files and {len(video_files)} video files"
        )

        # Compose each scene
        composed_scenes = []
        for i, (audio_file, video_file) in enumerate(zip(audio_files, video_files)):
            try:
                composed_path = compose_single_scene(audio_file, video_file, i)
                composed_scenes.append(composed_path)
            except Exception as e:
                logger.error(f"Error composing scene {i}: {str(e)}")
                # Continue with other scenes

        if not composed_scenes:
            raise ValueError("No scenes were successfully composed")

        # Concatenate all scenes into final video
        final_video_path = concatenate_scenes(composed_scenes, job_id)

        # Upload final video to S3
        final_video_url = upload_final_video(final_video_path, job_id)

        # Cleanup temporary files
        cleanup_temp_files(composed_scenes + [final_video_path])

        return final_video_url

    except Exception as e:
        logger.error(f"Error in compose_media: {str(e)}")
        raise


def download_media_files(job_id: str, folder_prefix: str) -> List[Dict[str, Any]]:
    """Download media files from S3 for a specific job"""
    try:
        # List objects in S3 with the job prefix
        prefix = f"{folder_prefix}/{job_id}/"
        response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)

        files = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = os.path.basename(key)

            # Extract scene number from filename
            scene_number = extract_scene_number(filename)
            if scene_number is None:
                logger.warning(f"Could not extract scene number from {filename}")
                continue

            # Download file to temp directory
            local_path = f"/tmp/{filename}"
            s3.download_file(S3_BUCKET, key, local_path)

            files.append(
                {
                    "scene_number": scene_number,
                    "local_path": local_path,
                    "filename": filename,
                    "s3_key": key,
                }
            )

        return files

    except Exception as e:
        logger.error(f"Error downloading media files: {str(e)}")
        return []


def extract_scene_number(filename: str) -> int | None:
    """Extract scene number from filename like 'scene_01_video.mp4'"""
    try:
        import re

        match = re.search(r"scene_(\d+)", filename)
        if match:
            return int(match.group(1))
        return None
    except:
        return None


def compose_single_scene(
    audio_file: Dict[str, Any], video_file: Dict[str, Any], scene_index: int
) -> str:
    """Compose a single scene using FFmpeg"""
    try:
        output_path = f"/tmp/composed_scene_{scene_index:02d}.mp4"  # FFmpeg command to compose audio and video
        # Use FFmpeg from layer if available, fallback to system ffmpeg
        ffmpeg_path = (
            "/opt/bin/ffmpeg" if os.path.exists("/opt/bin/ffmpeg") else "ffmpeg"
        )

        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            video_file["local_path"],  # Video input
            "-i",
            audio_file["local_path"],  # Audio input
            "-c:v",
            "libx264",  # Video codec
            "-c:a",
            "aac",  # Audio codec
            "-strict",
            "experimental",
            "-shortest",  # Use shortest duration
            "-map",
            "0:v:0",  # Map first video stream
            "-map",
            "1:a:0",  # Map first audio stream
            "-r",
            "30",  # Frame rate
            "-preset",
            "fast",  # Encoding preset
            output_path,
        ]

        logger.info(f"Composing scene {scene_index} with command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed with return code {result.returncode}")

        if not os.path.exists(output_path):
            raise RuntimeError(f"Output file was not created: {output_path}")

        logger.info(f"Successfully composed scene {scene_index}")
        return output_path

    except Exception as e:
        logger.error(f"Error composing scene {scene_index}: {str(e)}")
        raise


def concatenate_scenes(scene_paths: List[str], job_id: str) -> str:
    """Concatenate all composed scenes into a single video"""
    try:
        # Create file list for FFmpeg concat
        concat_file = f"/tmp/concat_list_{job_id}.txt"
        with open(concat_file, "w") as f:
            for path in scene_paths:
                f.write(f"file '{path}'\n")

        output_path = f"/tmp/final_video_{job_id}.mp4"  # FFmpeg concat command
        # Use FFmpeg from layer if available, fallback to system ffmpeg
        ffmpeg_path = (
            "/opt/bin/ffmpeg" if os.path.exists("/opt/bin/ffmpeg") else "ffmpeg"
        )

        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
            "-c",
            "copy",  # Copy streams without re-encoding
            output_path,
        ]

        logger.info(f"Concatenating scenes with command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            logger.error(f"FFmpeg concat error: {result.stderr}")
            raise RuntimeError(
                f"FFmpeg concat failed with return code {result.returncode}"
            )

        if not os.path.exists(output_path):
            raise RuntimeError(f"Final video was not created: {output_path}")

        logger.info(f"Successfully concatenated {len(scene_paths)} scenes")
        return output_path

    except Exception as e:
        logger.error(f"Error concatenating scenes: {str(e)}")
        raise


def upload_final_video(video_path: str, job_id: str) -> str:
    """Upload final composed video to S3"""
    try:
        s3_key = f"final-videos/{job_id}/final_video.mp4"

        # Upload to S3
        s3.upload_file(
            video_path,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": "video/mp4",
                "Metadata": {"job_id": job_id, "created_at": str(int(time.time()))},
            },
        )

        # Generate S3 URL
        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"

        logger.info(f"Final video uploaded to: {s3_url}")
        return s3_url

    except Exception as e:
        logger.error(f"Error uploading final video: {str(e)}")
        raise


def cleanup_temp_files(file_paths: List[str]):
    """Clean up temporary files"""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Cleaned up temp file: {path}")
        except Exception as e:
            logger.warning(f"Could not clean up {path}: {str(e)}")
