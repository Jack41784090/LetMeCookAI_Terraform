import json
import os
import boto3
import logging
import fal_client
import time
from typing import Any, Dict, List
import re
import requests
from urllib.parse import urlparse
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sqs = boto3.client("sqs", region_name="us-east-2")
s3 = boto3.client("s3", region_name="us-east-2")
dynamodb = boto3.client("dynamodb", region_name="us-east-2")
lambda_client = boto3.client("lambda", region_name="us-east-2")

# Environment variables
SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL")
S3_BUCKET = os.environ.get("S3_BUCKET")
FAL_KEY = os.environ.get("FAL_KEY")
JOB_COORDINATION_TABLE = os.environ.get("JOB_COORDINATION_TABLE")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to process both video and audio generation requests from SQS messages.

    Args:
        event: SQS event containing messages from request_script
        context: Lambda context object

    Returns:
        Response indicating processing status
    """
    try:
        processed_count = 0
        failed_count = 0

        logger.info(f"Received event: {json.dumps(event, default=str)}")

        # Check if this is a direct event (for testing) or SQS event
        if "Records" in event:
            # Process SQS records
            logger.info(f"Processing {len(event['Records'])} SQS records")
            records_to_process = event["Records"]
        else:
            # Direct event for testing - wrap it as a single record
            logger.info("Processing direct event (test mode)")
            records_to_process = [{"body": json.dumps(event)}]
        # Process each record
        for record in records_to_process:
            job_id = None  # Initialize job_id for error handling
            try:
                # Parse the SQS message body
                message_body = json.loads(record["body"])
                logger.info(f"Processing message: {message_body}")
                # Extract data from the message
                prompt = message_body.get("prompt")
                role = message_body.get("role")
                response = message_body.get("response")
                type = message_body.get("type")

                if not all([prompt, role, response, type]):
                    logger.error("Missing required fields in message")
                    failed_count += 1
                    continue

                # Parse the AI response to extract scenes
                scenes = extract_scenes_from_response(response)

                if not scenes:
                    logger.error("No scenes found in AI response")
                    failed_count += 1
                    continue

                # Generate shared job ID
                job_id = generate_shared_job_id(prompt)

                # Initialize job coordination
                if JOB_COORDINATION_TABLE:
                    initialize_job_coordination(
                        job_id, JOB_COORDINATION_TABLE, prompt, role
                    )

                # Generate both video and audio in parallel
                video_results, audio_results = asyncio.run(
                    generate_media_parallel(scenes, prompt, role, job_id, type)
                )

                # Store results
                store_combined_results(
                    video_results, audio_results, prompt, role, response, job_id
                )

                # Update job coordination status to complete and trigger composition
                if JOB_COORDINATION_TABLE:
                    update_job_coordination_status(
                        job_id, "video_audio", "complete", JOB_COORDINATION_TABLE
                    )

                processed_count += 1
                logger.info(f"Successfully processed message with {len(scenes)} scenes")

            except Exception as e:
                logger.error(f"Error processing SQS record: {str(e)}")
                # Update job coordination status to failed if job_id exists and table is available
                try:
                    if job_id and JOB_COORDINATION_TABLE:
                        update_job_coordination_status(
                            job_id, "video_audio", "failed", JOB_COORDINATION_TABLE
                        )
                except:
                    pass  # Don't fail on coordination update errors
                failed_count += 1
                continue

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": f"Processed {processed_count} messages successfully, {failed_count} failed",
                    "processed": processed_count,
                    "failed": failed_count,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "details": str(e)}),
        }


async def generate_media_parallel(
    scenes: List[Dict[str, Any]], original_prompt: str, role: str, job_id: str, type: str
) -> tuple:
    """
    Generate both video and audio in parallel using asyncio

    Returns:
        Tuple of (video_results, audio_results)
    """
    logger.info(f"Starting async parallel media generation for job: {job_id}")

    # Start both video and audio generation concurrently
    video_task = generate_videos_for_scenes(scenes, original_prompt, role, job_id, type)
    audio_task = generate_audio_for_scenes(scenes, original_prompt, role, job_id) if type != "short" else asyncio.sleep(0)

    # Wait for both to complete
    video_results, audio_results = await asyncio.gather(video_task, audio_task)

    logger.info(f"Completed async parallel media generation for job: {job_id}")
    return video_results, audio_results


def extract_scenes_from_response(response) -> List[Dict[str, Any]]:
    """Extract scene descriptions from the AI response."""
    scenes = []

    try:
        # Parse the JSON response from the AI
        if isinstance(response, dict):
            parsed_response = response
        else:
            parsed_response = json.loads(response)

        # Handle structured video script format
        if isinstance(parsed_response, dict) and "scenes" in parsed_response:
            video_scenes = parsed_response["scenes"]
            for scene in video_scenes:
                scene_data = {
                    "scene_number": scene.get("scene_number", 1),
                    "duration": scene.get("duration_seconds", 10),
                    "visual_description": scene.get("visual_description", ""),
                    "voiceover": scene.get("voiceover", ""),
                    "positive_prompt": scene.get(
                        "positive_prompt", scene.get("visual_description", "")
                    ),
                    "negative_prompt": scene.get("negative_prompt", ""),
                    "topic": parsed_response.get("topic", "Unknown"),
                    "title": parsed_response.get("title", "Unknown"),
                    "master_prompt_context": parsed_response.get(
                        "master_prompt_context", {}
                    ),
                }
                scenes.append(scene_data)

            logger.info(
                f"Extracted {len(scenes)} structured scenes from video script JSON"
            )
            return scenes

        # Handle simple list/dict formats
        elif isinstance(parsed_response, list):
            return [
                {"description": scene, "voiceover": scene, "duration": 10}
                for scene in parsed_response
            ]
        elif isinstance(parsed_response, dict):
            for key, value in parsed_response.items():
                if "scene" in key.lower() and isinstance(value, list):
                    return [
                        {"description": scene, "voiceover": scene, "duration": 10}
                        for scene in value
                    ]

    except json.JSONDecodeError:
        logger.warning("Response is not valid JSON, attempting text parsing")

        if isinstance(response, str):
            # Text parsing fallback
            scene_patterns = [
                r"Scene \d+[:\-]\s*(.+?)(?=Scene \d+|$)",
                r"\d+\.\s*(.+?)(?=\d+\.|$)",
                r"- (.+?)(?=\n-|$)",
            ]

            for pattern in scene_patterns:
                matches = re.findall(pattern, response, re.MULTILINE | re.DOTALL)
                if matches:
                    scenes = [
                        {
                            "description": match.strip(),
                            "voiceover": match.strip(),
                            "duration": 10,
                        }
                        for match in matches
                        if match.strip()
                    ]
                    break

            if not scenes:
                paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
                if len(paragraphs) > 1:
                    scenes = [
                        {"description": para, "voiceover": para, "duration": 10}
                        for para in paragraphs
                    ]
                else:
                    sentences = [
                        s.strip()
                        for s in response.split(".")
                        if s.strip() and len(s.strip()) > 20
                    ]
                    scenes = [
                        {
                            "description": sentence + ".",
                            "voiceover": sentence + ".",
                            "duration": 8,
                        }
                        for sentence in sentences[:5]
                    ]

            logger.info(f"Extracted {len(scenes)} scenes from text parsing")

    except Exception as e:
        logger.error(f"Error extracting scenes: {str(e)}")

    return scenes


async def generate_videos_for_scenes(
    scenes: List[Dict[str, Any]], original_prompt: str, role: str, job_id: str, type: str
) -> List[Dict[str, Any]]:
    """Generate videos for each scene using external API concurrently."""
    logger.info(f"Generating videos concurrently for job: {job_id}")

    # Create all video generation tasks
    tasks = []
    for i, scene in enumerate(scenes):
        task = generate_single_video(scene, i, job_id, type)
        tasks.append(task)

    # Run all tasks concurrently
    video_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and handle exceptions
    processed_results = []
    for i, result in enumerate(video_results):
        if isinstance(result, Exception):
            logger.error(f"Error generating video for scene {i+1}: {str(result)}")
            scene = scenes[i]
            processed_results.append(
                {
                    "scene_index": i,
                    "scene_number": scene.get("scene_number", i + 1),
                    "scene_description": scene.get(
                        "visual_description", scene.get("description", "")
                    ),
                    "voiceover": scene.get("voiceover", ""),
                    "duration": scene.get("duration", 10),
                    "video_result": None,
                    "status": "failed",
                    "error": str(result),
                }
            )
        else:
            processed_results.append(result)

    return processed_results


def get_video_request(scene: Dict[str, Any], type: str) -> Dict[str, Any]:
    """Prepare video generation request."""

    scene_description = (
        scene.get("master_prompt_context", {}).get("positive_prefix", "")
        + " "
        + scene.get("positive_prompt", scene.get("visual_description", ""))
    )
    return {
        "model": "fal-ai/bytedance/seedance/v1/pro/text-to-video",
        "prompt": scene_description,
        "aspect_ratio": "9:16",
        "resolution": "480p",
        "duration": scene.get("duration", 5),
        "camera_fixed": False,
        "seed": -1,
    } if type == "short" else {
        "model": "fal-ai/minimax/hailuo-02/standard/text-to-video",
        "prompt": scene_description,
    }

async def generate_single_video(
    scene: Dict[str, Any], scene_index: int, job_id: str, type: str
) -> Dict[str, Any]:
    """Generate a single video asynchronously."""
    try:
        # Get scene description
        scene_number = scene.get("scene_number", scene_index + 1)
        visual_desc = scene.get("visual_description", "")
        voiceover = scene.get("voiceover", "")

        logger.info(
            f"Generating video for scene {scene_number}: {visual_desc[:100]}..."
        )

        # Prepare video generation request
        video_request = get_video_request(scene, type)


        # Make async request to external video generation API
        video_result = await call_video_generation_api_async(
            video_request, job_id, scene_number
        )

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "scene_description": visual_desc,
            "voiceover": voiceover,
            "duration": scene.get("duration"),
            "video_request": video_request,
            "video_result": video_result,
            "status": "success" if video_result.get("success") else "failed",
        }

    except Exception as e:
        logger.error(f"Error generating video for scene {scene_index+1}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene.get("scene_number", scene_index + 1),
            "scene_description": scene.get(
                "visual_description", scene.get("description", "")
            ),
            "voiceover": scene.get("voiceover", ""),
            "duration": scene.get("duration", 10),
            "video_result": None,
            "status": "failed",
            "error": str(e),
        }


async def generate_audio_for_scenes(
    scenes: List[Dict[str, Any]], original_prompt: str, role: str, job_id: str
) -> List[Dict[str, Any]]:
    """Generate audio for each scene using external API concurrently."""
    logger.info(f"Generating audio concurrently for job: {job_id}")

    # Create all audio generation tasks
    tasks = []
    for i, scene in enumerate(scenes):
        task = generate_single_audio(scene, i, job_id)
        tasks.append(task)

    # Run all tasks concurrently
    audio_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and handle exceptions
    processed_results = []
    for i, result in enumerate(audio_results):
        if isinstance(result, Exception):
            logger.error(f"Error generating audio for scene {i+1}: {str(result)}")
            scene = scenes[i]
            processed_results.append(
                {
                    "scene_index": i,
                    "scene_number": scene.get("scene_number", i + 1),
                    "voiceover_text": scene.get(
                        "voiceover", scene.get("description", "")
                    ),
                    "visual_description": scene.get("visual_description", ""),
                    "duration": scene.get("duration", 10),
                    "audio_result": None,
                    "status": "failed",
                    "error": str(result),
                }
            )
        else:
            processed_results.append(result)

    return processed_results


async def generate_single_audio(
    scene: Dict[str, Any], scene_index: int, job_id: str
) -> Dict[str, Any]:
    """Generate a single audio track asynchronously."""
    try:
        # Get voiceover text
        if "voiceover" in scene:
            voiceover_text = scene["voiceover"]
            scene_number = scene.get("scene_number", scene_index + 1)
            duration = scene.get("duration", 10)
            visual_desc = scene.get("visual_description", "")
        else:
            voiceover_text = scene.get("description", "")
            scene_number = scene_index + 1
            duration = scene.get("duration", 10)
            visual_desc = voiceover_text

        logger.info(
            f"Generating audio for scene {scene_number}: {voiceover_text[:100]}..."
        )

        # Skip if no voiceover text
        if not voiceover_text.strip():
            logger.warning(f"No voiceover text for scene {scene_number}, skipping")
            return {
                "scene_index": scene_index,
                "scene_number": scene_number,
                "voiceover_text": "",
                "visual_description": visual_desc,
                "duration": duration,
                "audio_result": None,
                "status": "skipped",
                "message": "No voiceover text provided",
            }

        # Prepare audio generation request
        audio_request = {
            "prompt": voiceover_text,
            "voice": "hf_alpha",
            "speed": 1.0,
        }

        # Voice mapping from master context
        if "master_prompt_context" in scene:
            master_context = scene["master_prompt_context"][""]
            if master_context.get("voice_style"):
                voice_mapping = {
                    "female_alpha": "hf_alpha",
                    "female_beta": "hf_beta",
                    "male_omega": "hm_omega",
                    "male_psi": "hm_psi",
                }
                audio_request["voice"] = voice_mapping.get(
                    master_context["voice_style"], "hf_alpha"
                )
            if master_context.get("speech_speed"):
                audio_request["speed"] = master_context["speech_speed"]

        # Make async request to external audio generation API
        audio_result = await call_audio_generation_api_async(
            audio_request, job_id, scene_number
        )

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "voiceover_text": voiceover_text,
            "visual_description": visual_desc,
            "duration": duration,
            "audio_request": audio_request,
            "audio_result": audio_result,
            "status": "success" if audio_result.get("success") else "failed",
        }

    except Exception as e:
        logger.error(f"Error generating audio for scene {scene_index+1}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene.get("scene_number", scene_index + 1),
            "voiceover_text": scene.get("voiceover", scene.get("description", "")),
            "visual_description": scene.get("visual_description", ""),
            "duration": scene.get("duration", 10),
            "audio_result": None,
            "status": "failed",
            "error": str(e),
        }


async def call_video_generation_api_async(
    video_request: Dict[str, Any], job_id: str, scene_number: int
) -> Dict[str, Any]:
    """Call video generation API asynchronously"""
    try:
        if not FAL_KEY:
            logger.error("FAL_KEY environment variable not set")
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY

        if not video_request.get("prompt"):
            logger.error(f"No prompt provided for scene {scene_number}")
            return {"error": "No prompt provided for video generation"}

        arguments = {
            "prompt": video_request.get("prompt"),
            "aspect_ratio": video_request.get("aspect_ratio", "9:16"),
            "resolution": video_request.get("resolution", "480p"),
            "duration": video_request.get("duration", 5),
            "camera_fixed": video_request.get("camera_fixed", False),
        }

        # Submit async request
        handler = await fal_client.submit_async(
            video_request["model"],
            arguments=arguments,
        )

        # Process events with logs
        async for event in handler.iter_events(with_logs=True):
            if hasattr(event, "logs"):
                for log in event.logs:
                    logger.info(
                        f"Scene {scene_number} video generation: {log.get('message', str(log))}"
                    )

        # Get final result
        result = await handler.get()
        logger.info(f"Scene {scene_number} video generation completed: {result}")

        if result and "video" in result and "url" in result["video"]:
            video_url = result["video"]["url"]

            # Generate S3 key
            parsed_url = urlparse(video_url)
            filename = (
                os.path.basename(parsed_url.path) or f"scene_{scene_number:02d}.mp4"
            )
            if not filename.startswith(f"scene_{scene_number:02d}"):
                name, ext = os.path.splitext(filename)
                filename = f"scene_{scene_number:02d}_{name}{ext}"

            s3_key = f"generated-videos/{job_id}/{filename}"

            # Download and store
            download_result = download_video_to_s3(video_url, s3_key)

            response_data = {"original_video_url": video_url, "success": True}

            if download_result["success"]:
                response_data.update(
                    {
                        "s3_key": download_result["s3_key"],
                        "s3_url": download_result["s3_url"],
                        "stored_in_s3": True,
                    }
                )
            else:
                response_data.update(
                    {"stored_in_s3": False, "download_error": download_result["error"]}
                )

            return response_data
        else:
            return {"error": "No video URL in response", "details": result}

    except Exception as e:
        logger.error(
            f"Error calling async video API for scene {scene_number}: {str(e)}"
        )
        return {"error": "API call failed", "details": str(e)}


async def call_audio_generation_api_async(
    audio_request: Dict[str, Any], job_id: str, scene_number: int
) -> Dict[str, Any]:
    """Call audio generation API asynchronously"""
    try:
        if not FAL_KEY:
            logger.error("FAL_KEY environment variable not set")
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY

        # Submit async request
        handler = await fal_client.submit_async(
            "fal-ai/kokoro/hindi",
            arguments={
                "prompt": audio_request["prompt"],
                "voice": audio_request["voice"],
            },
        )

        # Process events with logs
        async for event in handler.iter_events(with_logs=True):
            if hasattr(event, "logs"):
                for log in event.logs:
                    logger.info(
                        f"Scene {scene_number} audio generation: {log.get('message', str(log))}"
                    )

        # Get final result
        result = await handler.get()
        logger.info(f"Scene {scene_number} audio generation completed: {result}")

        if result and "audio" in result and "url" in result["audio"]:
            audio_url = result["audio"]["url"]

            # Generate S3 key
            parsed_url = urlparse(audio_url)
            filename = (
                os.path.basename(parsed_url.path) or f"scene_{scene_number:02d}.wav"
            )
            if not filename.startswith(f"scene_{scene_number:02d}"):
                name, ext = os.path.splitext(filename)
                if not ext:
                    ext = ".wav"
                filename = f"scene_{scene_number:02d}_{name}{ext}"

            s3_key = f"generated-audio/{job_id}/{filename}"

            # Download and store
            download_result = download_audio_to_s3(audio_url, s3_key)

            response_data = {"original_audio_url": audio_url, "success": True}

            if download_result["success"]:
                response_data.update(
                    {
                        "s3_key": download_result["s3_key"],
                        "s3_url": download_result["s3_url"],
                        "stored_in_s3": True,
                    }
                )
            else:
                response_data.update(
                    {"stored_in_s3": False, "download_error": download_result["error"]}
                )

            return response_data
        else:
            return {"error": "No audio URL in response", "details": result}

    except Exception as e:
        logger.error(
            f"Error calling async audio API for scene {scene_number}: {str(e)}"
        )
        return {"error": "API call failed", "details": str(e)}


def download_video_to_s3(video_url: str, s3_key: str) -> Dict[str, Any]:
    """Download video from URL and store it in S3."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")

        logger.info(f"Downloading video from: {video_url}")

        response = requests.get(video_url, stream=True, timeout=300)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "video/mp4")
        content_length = response.headers.get("content-length")

        s3.upload_fileobj(
            response.raw,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {
                    "source_url": video_url,
                    "download_timestamp": str(int(time.time())),
                },
            },
        )

        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Video successfully uploaded to S3: {s3_url}")

        return {
            "success": True,
            "s3_key": s3_key,
            "s3_url": s3_url,
            "content_type": content_type,
            "size_bytes": content_length,
        }

    except Exception as e:
        logger.error(f"Error downloading/uploading video: {str(e)}")
        return {"success": False, "error": str(e)}


def download_audio_to_s3(audio_url: str, s3_key: str) -> Dict[str, Any]:
    """Download audio from URL and store it in S3."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")

        logger.info(f"Downloading audio from: {audio_url}")

        response = requests.get(audio_url, stream=True, timeout=300)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "audio/wav")
        content_length = response.headers.get("content-length")

        s3.upload_fileobj(
            response.raw,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {
                    "source_url": audio_url,
                    "download_timestamp": str(int(time.time())),
                },
            },
        )

        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Audio successfully uploaded to S3: {s3_url}")

        return {
            "success": True,
            "s3_key": s3_key,
            "s3_url": s3_url,
            "content_type": content_type,
            "size_bytes": content_length,
        }

    except Exception as e:
        logger.error(f"Error downloading/uploading audio: {str(e)}")
        return {"success": False, "error": str(e)}


def store_combined_results(
    video_results: List[Dict[str, Any]],
    audio_results: List[Dict[str, Any]],
    prompt: str,
    role: str,
    ai_response: str,
    job_id: str,
) -> None:
    """Store combined generation results in S3."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")

        job_summary = {
            "job_id": job_id,
            "timestamp": int(time.time()),
            "original_prompt": prompt,
            "role": role,
            "ai_response": ai_response,
            "total_scenes": len(video_results),
            "video_results": video_results,
            "audio_results": audio_results,
            "successful_videos": len(
                [r for r in video_results if r["status"] == "success"]
            ),
            "successful_audio": len(
                [r for r in audio_results if r["status"] == "success"]
            ),
            "failed_videos": len([r for r in video_results if r["status"] == "failed"]),
            "failed_audio": len([r for r in audio_results if r["status"] == "failed"]),
        }

        s3_key = f"combined-generations/{job_id}/results.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(job_summary, indent=2),
            ContentType="application/json",
        )
        logger.info(f"Stored combined results in S3: {s3_key}")

    except Exception as e:
        logger.error(f"Error storing combined results: {str(e)}")


# Job coordination functions
def generate_shared_job_id(original_prompt: str) -> str:
    """Generate a shared job ID for media generation"""
    return f"job_{int(time.time())}_{hash(original_prompt) % 10000}"


def initialize_job_coordination(
    job_id: str, table_name: str, prompt: str, role: str
) -> None:
    """Initialize job coordination record"""
    try:
        if not table_name:
            logger.warning("No coordination table specified")
            return

        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        dynamodb.put_item(
            TableName=table_name,
            Item={
                "job_id": {"S": job_id},
                "created_at": {"N": str(int(time.time()))},
                "expires_at": {"N": str(expires_at)},
                "original_prompt": {"S": prompt},
                "role": {"S": role},
                "video_audio_status": {"S": "pending"},
                "composition_status": {"S": "pending"},
            },
        )

        logger.info(f"Initialized job coordination for {job_id}")

    except Exception as e:
        logger.error(f"Error initializing job coordination: {str(e)}")


def update_job_coordination_status(
    job_id: str, component: str, status: str, table_name: str
) -> None:
    """Update job coordination status and trigger composition if ready"""
    try:
        if not table_name:
            logger.warning("No coordination table specified")
            return

        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        dynamodb.update_item(
            TableName=table_name,
            Key={"job_id": {"S": job_id}},
            UpdateExpression=f"SET {component}_status = :status, {component}_updated_at = :timestamp, expires_at = :expires",
            ExpressionAttributeValues={
                ":status": {"S": status},
                ":timestamp": {"N": str(int(time.time()))},
                ":expires": {"N": str(expires_at)},
            },
        )

        logger.info(
            f"Updated {component}_status = {status} for job {job_id}"
        )  # If video_audio is complete, trigger composition
        if component == "video_audio" and status == "complete":
            logger.info(
                f"Both video and audio ready for job {job_id}, triggering composition"
            )

            try:
                compose_function_name = os.environ.get("COMPOSE_FUNCTION_NAME")
                if not compose_function_name:
                    logger.error("COMPOSE_FUNCTION_NAME environment variable not set")
                    return

                lambda_client.invoke(
                    FunctionName=compose_function_name,
                    InvocationType="Event",
                    Payload=json.dumps({"job_id": job_id}),
                )
                logger.info(f"Successfully triggered composition for job {job_id}")
            except Exception as e:
                logger.error(
                    f"Failed to trigger composition for job {job_id}: {str(e)}"
                )

    except Exception as e:
        logger.error(f"Error updating job coordination status: {str(e)}")
