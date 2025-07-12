import json
import os
import boto3
import logging
import time
import subprocess
import re
from typing import Any, Dict, List, Optional

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
YOUTUBE_UPLOAD_FUNCTION_NAME = os.environ.get("YOUTUBE_UPLOAD_FUNCTION_NAME")

# Constants
FFMPEG_PATH = "/opt/bin/ffmpeg" if os.path.exists("/opt/bin/ffmpeg") else "ffmpeg"
BACKGROUND_MUSIC = {
    "bucket": "letmecook-ai-generated-videos",
    "key": "Keejo Kesari Ke Laal - cut.mp3",
}
SUBSCRIBE_AND_LIKE_ANIMATION = {
    "bucket": "letmecook-ai-generated-videos",
    "key": "arrow_animation.mp4",
}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda function to compose audio and video when both are ready."""
    try:
        job_id = event.get("job_id")
        if not job_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "job_id is required"}),
            }

        response_obj = event.get("response", {})
        video_type = event.get("video_type", "regular")

        logger.info(f"Starting composition for job: {job_id}, type: {video_type}")

        # Check if media is ready for composition
        if not is_media_ready(job_id):
            logger.info(f"Job {job_id} not ready for composition yet")
            return {
                "statusCode": 200,
                "body": json.dumps({"message": "Waiting for completion"}),
            }

        # Update status and compose media
        update_job_status(job_id, "composition_status", "in_progress")
        composed_video_url = compose_media(job_id, video_type)

        # Update final status and trigger upload
        update_job_status(job_id, "composition_status", "complete")
        update_job_status(job_id, "final_video_url", composed_video_url)
        trigger_youtube_upload(job_id, response_obj, video_type)

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
            update_job_status(locals()["job_id"], "composition_status", "failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Composition failed", "details": str(e)}),
        }


def is_media_ready(job_id: str) -> bool:
    """Check if media generation is complete."""
    try:
        response = dynamodb.get_item(
            TableName=JOB_COORDINATION_TABLE, Key={"job_id": {"S": job_id}}
        )

        if "Item" not in response:
            logger.warning(f"Job {job_id} not found in DynamoDB")
            return False

        item = response["Item"]
        video_audio_status = item.get("video_audio_status", {}).get("S", "")
        logger.info(f"Job {job_id} video_audio_status: '{video_audio_status}'")

        return video_audio_status == "complete"

    except Exception as e:
        logger.error(f"Error checking job status: {str(e)}")
        return False


def update_job_status(job_id: str, field: str, value: str) -> None:
    """Update job status in DynamoDB with TTL."""
    try:
        expires_at = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days TTL

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


def compose_media(job_id: str, video_type: str = "regular") -> str:
    """Download and compose media files, return final video URL."""
    try:
        video_files = download_media_files(job_id, "generated-videos")
        if not video_files:
            raise ValueError("Missing video files")

        video_files.sort(key=lambda x: x["scene_number"])

        if video_type == "short":
            final_video_path = process_short_video(video_files, job_id)
        else:
            audio_files = download_media_files(job_id, "generated-audio")
            if not audio_files:
                raise ValueError("Missing audio files")

            audio_files.sort(key=lambda x: x["scene_number"])
            final_video_path = process_regular_video(audio_files, video_files, job_id)

        # Upload and cleanup
        final_video_url = upload_final_video(final_video_path, job_id)
        cleanup_temp_files([final_video_path] + [f["local_path"] for f in video_files])

        return final_video_url

    except Exception as e:
        logger.error(f"Error in compose_media: {str(e)}")
        raise


def download_media_files(job_id: str, folder_prefix: str) -> List[Dict[str, Any]]:
    """Download media files from S3 for a specific job."""
    try:
        prefix = f"{folder_prefix}/{job_id}/"
        response = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)

        files = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = os.path.basename(key)
            scene_number = extract_scene_number(filename)

            if scene_number is None:
                logger.warning(f"Could not extract scene number from {filename}")
                continue

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


def extract_scene_number(filename: str) -> Optional[int]:
    """Extract scene number from filename like 'scene_01_video.mp4'."""
    match = re.search(r"scene_(\d+)", filename)
    return int(match.group(1)) if match else None


def upload_final_video(video_path: str, job_id: str) -> str:
    """Upload final composed video to S3."""
    try:
        s3_key = f"final-videos/{job_id}/final_video.mp4"

        s3.upload_file(
            video_path,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": "video/mp4",
                "Metadata": {"job_id": job_id, "created_at": str(int(time.time()))},
            },
        )

        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Final video uploaded to: {s3_url}")
        return s3_url

    except Exception as e:
        logger.error(f"Error uploading final video: {str(e)}")
        raise


def cleanup_temp_files(file_paths: List[str]) -> None:
    """Clean up temporary files."""
    for path in file_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Could not clean up {path}: {str(e)}")


def process_regular_video(
    audio_files: List[Dict[str, Any]], video_files: List[Dict[str, Any]], job_id: str
) -> str:
    """Process regular video by composing audio and video scenes."""
    logger.info(
        f"Processing {len(audio_files)} audio and {len(video_files)} video files"
    )

    if len(audio_files) != len(video_files):
        raise ValueError(
            f"Mismatch: {len(audio_files)} audio vs {len(video_files)} video files"
        )

    if len(audio_files) == 0:
        raise ValueError("No scenes to process")

    if len(audio_files) == 1:
        # Single scene - compose directly
        final_video_path = f"/tmp/final_video_{job_id}.mp4"
        run_ffmpeg_command(
            [
                FFMPEG_PATH,
                "-y",
                "-i",
                video_files[0]["local_path"],
                "-i",
                audio_files[0]["local_path"],
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-shortest",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-r",
                "24",
                "-threads",
                "1",
                final_video_path,
            ]
        )
        return final_video_path

    # Multiple scenes - compose and concatenate
    concat_file = f"/tmp/concat_list_{job_id}.txt"
    scene_files = []

    with open(concat_file, "w") as f:
        for i, (audio, video) in enumerate(zip(audio_files, video_files)):
            scene_path = f"/tmp/composed_scene_{i:02d}.mp4"
            scene_files.append(scene_path)

            run_ffmpeg_command(
                [
                    FFMPEG_PATH,
                    "-y",
                    "-i",
                    video["local_path"],
                    "-i",
                    audio["local_path"],
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "28",
                    "-shortest",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-r",
                    "24",
                    "-threads",
                    "1",
                    scene_path,
                ]
            )

            f.write(f"file '{scene_path}'\n")

    # Concatenate all scenes
    final_video_path = f"/tmp/final_video_{job_id}.mp4"
    run_ffmpeg_command(
        [
            FFMPEG_PATH,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file,
            "-c",
            "copy",
            "-threads",
            "1",
            final_video_path,
        ]
    )

    cleanup_temp_files(scene_files + [concat_file])
    return final_video_path


def process_short_video(video_files: List[Dict[str, Any]], job_id: str) -> str:
    """Process short video by adding background music."""
    logger.info(f"Processing short video with {len(video_files)} files")

    mp3_path = f"/tmp/background_music_{job_id}.mp3"
    s3.download_file(BACKGROUND_MUSIC["bucket"], BACKGROUND_MUSIC["key"], mp3_path)
    
    endscreen_path = f"/tmp/subscribe_and_like_{job_id}.mp4"
    s3.download_file(SUBSCRIBE_AND_LIKE_ANIMATION["bucket"], SUBSCRIBE_AND_LIKE_ANIMATION["key"], endscreen_path)
    
    # main video concatenation
    if len(video_files) > 1:
        concat_file = f"/tmp/video_concat_list_{job_id}.txt"
        with open(concat_file, "w") as f:
            for video_file in video_files:
                f.write(f"file '{video_file['local_path']}'\n")

        final_video_path = f"/tmp/concatenated_video_{job_id}.mp4"
        run_ffmpeg_command(
            [
                FFMPEG_PATH,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                "-threads", "1",
                final_video_path,
            ]
        )
    else:
        final_video_path = video_files[0]["local_path"]
    
    # Create concat file for main video + endscreen
    endscreen_concat_file = f"/tmp/endscreen_concat_{job_id}.txt"
    with open(endscreen_concat_file, "w") as f:
        f.write(f"file '{final_video_path}'\n")
        f.write(f"file '{endscreen_path}'\n")
    
    final_video_with_endscreen = f"/tmp/final_video_with_endscreen_{job_id}.mp4"
    run_ffmpeg_command([
        FFMPEG_PATH,
        "-y",
        "-f", "concat",
        "-safe", "0", 
        "-i", endscreen_concat_file,
        "-c", "copy",
        "-threads", "1",
        final_video_with_endscreen,
    ])
    
    # Add background music
    final_video_with_music = f"/tmp/final_video_with_music_{job_id}.mp4"
    run_ffmpeg_command(
        [
            FFMPEG_PATH,
            "-y",
            "-i", final_video_with_endscreen,
            "-i", mp3_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-r", "24",
            "-threads", "1",
            final_video_with_music,
        ]
    )

    cleanup_temp_files([mp3_path, endscreen_path, endscreen_concat_file, final_video_path])
    return final_video_with_endscreen


def run_ffmpeg_command(cmd: List[str]) -> None:
    """Execute FFmpeg command with error handling."""
    logger.info(f"Running FFmpeg: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        logger.error(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"FFmpeg failed with return code {result.returncode}")


def trigger_youtube_upload(
    job_id: str,
    response_obj: Optional[Dict[str, Any]] = None,
    video_type: str = "regular",
) -> None:
    """Trigger YouTube upload Lambda function."""
    try:
        if not YOUTUBE_UPLOAD_FUNCTION_NAME:
            logger.error("YOUTUBE_UPLOAD_FUNCTION_NAME not set")
            return

        payload = {"job_id": job_id, "video_type": video_type}
        if response_obj:
            payload["response"] = response_obj

        lambda_client.invoke(
            FunctionName=YOUTUBE_UPLOAD_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload),
        )

        logger.info(f"Triggered YouTube upload for job {job_id}")

    except Exception as e:
        logger.error(f"Failed to trigger YouTube upload: {str(e)}")
