from doctest import master
import json
import os
import boto3
import logging
import fal_client
import time
import asyncio
import requests
from typing import Any, Dict, List
from urllib.parse import urlparse

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
region = "us-east-2"
s3 = boto3.client("s3", region_name=region)
dynamodb = boto3.client("dynamodb", region_name=region)
lambda_client = boto3.client("lambda", region_name=region)

# Environment variables
S3_BUCKET = os.environ.get("S3_BUCKET")
FAL_KEY = os.environ.get("FAL_KEY")
JOB_COORDINATION_TABLE = os.environ.get("JOB_COORDINATION_TABLE")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process video and audio generation requests from SQS messages."""
    try:
        records = event.get("Records", [{"body": json.dumps(event)}])
        processed, failed = 0, 0

        for record in records:
            try:
                message = json.loads(record["body"])
                job_id = process_media_request(message)
                processed += 1
                logger.info(f"Successfully processed job: {job_id}")
            except Exception as e:
                logger.error(f"Failed to process record: {str(e)}")
                failed += 1

        return {
            "statusCode": 200,
            "body": json.dumps({"processed": processed, "failed": failed}),
        }
    except Exception as e:
        logger.error(f"Lambda handler error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def process_media_request(message: Dict[str, Any]) -> str:
    """Process a single media generation request."""
    # Extract and validate required fields
    prompt = message.get("prompt", "")
    role = message.get("role", "")
    response = message.get("response", "")
    video_type = message.get("type", "")

    if not all([prompt, role, response, video_type]):
        raise ValueError("Missing required fields: prompt, role, response, type")

    # Extract scenes and generate job ID
    scenes = extract_scenes(response)
    if not scenes:
        raise ValueError("No scenes found in AI response")

    job_id = f"job_{int(time.time())}_{hash(prompt) % 10000}"

    # Initialize job coordination
    initialize_job(job_id, prompt, role, video_type, str(response))

    # Generate media
    master_prompt = response.get("master_prompt_context")
    if not master_prompt:
        raise ValueError("Master prompt context missing in response")
    master_positive_prompt = master_prompt.get("positive_prefix")
    if not master_positive_prompt:
        raise ValueError("Master positive prompt missing in response")
    video_results, audio_results = asyncio.run(
        generate_media(scenes, job_id, video_type, master_positive_prompt)
    )

    # Store results and update status
    store_results(video_results, audio_results, prompt, role, str(response), job_id)
    complete_job(job_id, video_type, str(response))

    return job_id


def extract_scenes(response) -> List[Dict[str, Any]]:
    """Extract scene descriptions from AI response."""
    try:
        # Parse response if it's a string
        if isinstance(response, str):
            # Clean markdown formatting
            cleaned = response.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned)
        else:
            parsed = response

        # Extract scenes from structured format
        if isinstance(parsed, dict) and "scenes" in parsed:
            scenes = []
            for scene in parsed["scenes"]:
                scenes.append(
                    {
                        "scene_number": scene.get("scene_number", 1),
                        "duration": scene.get("duration_seconds", 10),
                        "visual_description": scene.get("visual_description", ""),
                        "voiceover": scene.get("voiceover", ""),
                        "positive_prompt": scene.get(
                            "positive_prompt", scene.get("visual_description", "")
                        ),
                        "negative_prompt": scene.get("negative_prompt", ""),
                        "master_prompt_context": parsed.get(
                            "master_prompt_context", {}
                        ),
                    }
                )
            return scenes
        else:
            raise ValueError("Response missing 'scenes' key")

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error extracting scenes: {str(e)}")
        raise


async def generate_media(
    scenes: List[Dict[str, Any]], job_id: str, video_type: str, master_prompt: str
) -> tuple:
    """Generate video and audio for all scenes in parallel."""
    logger.info(f"Starting media generation for job: {job_id}")

    # Create video generation tasks
    video_tasks = [
        generate_video(scene, i, job_id, video_type, master_prompt) for i, scene in enumerate(scenes)
    ]

    # For shorts, skip audio generation
    if video_type == "short":
        video_results = await asyncio.gather(*video_tasks, return_exceptions=True)
        return process_results(video_results, scenes), []

    # For regular videos, generate both video and audio
    audio_tasks = [generate_audio(scene, i, job_id) for i, scene in enumerate(scenes)]

    video_results, audio_results = await asyncio.gather(
        asyncio.gather(*video_tasks, return_exceptions=True),
        asyncio.gather(*audio_tasks, return_exceptions=True),
    )

    return process_results(video_results, scenes), process_results(
        audio_results, scenes
    )


def process_results(
    results: List, scenes: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Process generation results and handle exceptions."""
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Generation failed for scene {i+1}: {str(result)}")
            scene = scenes[i]
            processed.append(
                {
                    "scene_index": i,
                    "scene_number": scene.get("scene_number", i + 1),
                    "status": "failed",
                    "error": str(result),
                }
            )
        else:
            processed.append(result)
    return processed


async def generate_video(
    scene: Dict[str, Any], scene_index: int, job_id: str, video_type: str, master_prompt: str
) -> Dict[str, Any]:
    """Generate a single video asynchronously."""
    try:
        scene_number = scene.get("scene_number", scene_index + 1)
        visual_desc = scene.get("visual_description", "")

        logger.info(f"Generating video for scene {scene_number}")

        # Prepare video request
        video_request = get_video_request(scene, video_type, master_prompt)

        # Generate video
        video_result = await call_video_api(video_request, job_id, scene_number)

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "scene_description": visual_desc,
            "voiceover": scene.get("voiceover", ""),
            "duration": scene.get("duration"),
            "video_result": video_result,
            "status": "success" if video_result.get("success") else "failed",
        }
    except Exception as e:
        logger.error(f"Video generation failed for scene {scene_index+1}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene.get("scene_number", scene_index + 1),
            "status": "failed",
            "error": str(e),
        }


async def generate_audio(
    scene: Dict[str, Any], scene_index: int, job_id: str
) -> Dict[str, Any]:
    """Generate a single audio track asynchronously."""
    try:
        voiceover_text = scene.get("voiceover", "")
        scene_number = scene.get("scene_number", scene_index + 1)

        if not voiceover_text.strip():
            return {
                "scene_index": scene_index,
                "scene_number": scene_number,
                "status": "skipped",
                "message": "No voiceover text",
            }

        logger.info(f"Generating audio for scene {scene_number}")

        # Prepare audio request
        audio_request = {
            "prompt": voiceover_text,
            "voice": get_voice_setting(scene),
            "speed": get_speed_setting(scene),
        }

        # Generate audio
        audio_result = await call_audio_api(audio_request, job_id, scene_number)

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "voiceover_text": voiceover_text,
            "audio_result": audio_result,
            "status": "success" if audio_result.get("success") else "failed",
        }
    except Exception as e:
        logger.error(f"Audio generation failed for scene {scene_index+1}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene.get("scene_number", scene_index + 1),
            "status": "failed",
            "error": str(e),
        }


def get_video_request(scene: Dict[str, Any], video_type: str, master_prompt: str) -> Dict[str, Any]:
    """Prepare video generation request."""
    positive_prompt = scene.get("positive_prompt")
    scene_description = f"{positive_prompt} {master_prompt}".strip()

    if video_type == "short":
        return {
            "model": "fal-ai/bytedance/seedance/v1/pro/text-to-video",
            "prompt": scene_description,
            "aspect_ratio": "9:16",
            "resolution": "480p",
            "duration": scene.get("duration", 5),
            "camera_fixed": False,
            "seed": -1,
        }
    else:
        return {
            "model": "fal-ai/minimax/hailuo-02/standard/text-to-video",
            "prompt": scene_description,
            "aspect_ratio": "16:9",
            "duration": scene.get("duration", 10),
        }


def get_voice_setting(scene: Dict[str, Any]) -> str:
    """Get voice setting from scene context."""
    master_context = scene.get("master_prompt_context", {})
    voice_style = master_context.get("voice_style", "female_alpha")

    voice_mapping = {
        "female_alpha": "hf_alpha",
        "female_beta": "hf_beta",
        "male_omega": "hm_omega",
        "male_psi": "hm_psi",
    }
    return voice_mapping.get(voice_style, "hf_alpha")


def get_speed_setting(scene: Dict[str, Any]) -> float:
    """Get speech speed setting from scene context."""
    master_context = scene.get("master_prompt_context", {})
    return master_context.get("speech_speed", 1.0)


async def call_video_api(
    video_request: Dict[str, Any], job_id: str, scene_number: int
) -> Dict[str, Any]:
    """Call video generation API."""
    try:
        if not FAL_KEY:
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY

        # Submit async request
        handler = await fal_client.submit_async(
            video_request["model"],
            arguments={k: v for k, v in video_request.items() if k != "model"},
        )

        # Get result
        result = await handler.get()

        if result and "video" in result and "url" in result["video"]:
            video_url = result["video"]["url"]
            s3_key = f"generated-videos/{job_id}/scene_{scene_number:02d}.mp4"
            download_result = download_to_s3(video_url, s3_key, "video/mp4")

            return {"original_video_url": video_url, "success": True, **download_result}
        else:
            return {"error": "No video URL in response", "details": result}

    except Exception as e:
        logger.error(f"Video API error for scene {scene_number}: {str(e)}")
        return {"error": "API call failed", "details": str(e)}


async def call_audio_api(
    audio_request: Dict[str, Any], job_id: str, scene_number: int
) -> Dict[str, Any]:
    """Call audio generation API."""
    try:
        if not FAL_KEY:
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY

        # Submit async request
        handler = await fal_client.submit_async(
            "fal-ai/kokoro/hindi", arguments=audio_request
        )

        # Get result
        result = await handler.get()

        if result and "audio" in result and "url" in result["audio"]:
            audio_url = result["audio"]["url"]
            s3_key = f"generated-audio/{job_id}/scene_{scene_number:02d}.wav"
            download_result = download_to_s3(audio_url, s3_key, "audio/wav")

            return {"original_audio_url": audio_url, "success": True, **download_result}
        else:
            return {"error": "No audio URL in response", "details": result}

    except Exception as e:
        logger.error(f"Audio API error for scene {scene_number}: {str(e)}")
        return {"error": "API call failed", "details": str(e)}


def download_to_s3(url: str, s3_key: str, content_type: str) -> Dict[str, Any]:
    """Download file from URL and store in S3."""
    try:
        if not S3_BUCKET:
            return {"success": False, "error": "S3_BUCKET not configured"}

        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        s3.upload_fileobj(
            response.raw,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": content_type,
                "Metadata": {
                    "source_url": url,
                    "download_timestamp": str(int(time.time())),
                },
            },
        )

        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Successfully uploaded to S3: {s3_url}")

        return {
            "success": True,
            "s3_key": s3_key,
            "s3_url": s3_url,
            "stored_in_s3": True,
        }

    except Exception as e:
        logger.error(f"S3 upload error: {str(e)}")
        return {"success": False, "error": str(e)}


def initialize_job(
    job_id: str, prompt: str, role: str, video_type: str, ai_response: str
) -> None:
    """Initialize job coordination record."""
    try:
        if not JOB_COORDINATION_TABLE:
            logger.warning("No coordination table specified")
            return

        expires_at = int(time.time()) + (7 * 24 * 60 * 60)  # 7 days

        item = {
            "job_id": {"S": job_id},
            "created_at": {"N": str(int(time.time()))},
            "expires_at": {"N": str(expires_at)},
            "original_prompt": {"S": prompt},
            "role": {"S": role},
            "video_audio_status": {"S": "pending"},
            "composition_status": {"S": "pending"},
        }

        if video_type:
            item["video_type"] = {"S": video_type}

        # Extract video metadata from AI response
        if ai_response:
            try:
                response_data = (
                    ai_response
                    if isinstance(ai_response, dict)
                    else json.loads(ai_response)
                )
                response_obj = response_data.get("response", response_data)

                if "title" in response_obj:
                    item["video_title"] = {"S": response_obj["title"]}
                if "summary" in response_obj:
                    item["video_summary"] = {"S": response_obj["summary"]}
                if "hashtags" in response_obj and isinstance(
                    response_obj["hashtags"], list
                ):
                    item["video_hashtags"] = {"S": ",".join(response_obj["hashtags"])}
                if "topic" in response_obj:
                    item["video_topic"] = {"S": response_obj["topic"]}

                item["ai_response"] = {
                    "S": (
                        ai_response
                        if isinstance(ai_response, str)
                        else json.dumps(ai_response)
                    )
                }

            except Exception as e:
                logger.warning(f"Failed to extract video metadata: {str(e)}")

        dynamodb.put_item(TableName=JOB_COORDINATION_TABLE, Item=item)
        logger.info(f"Initialized job coordination for {job_id}")

    except Exception as e:
        logger.error(f"Error initializing job coordination: {str(e)}")


def store_results(
    video_results: List[Dict[str, Any]],
    audio_results: List[Dict[str, Any]],
    prompt: str,
    role: str,
    ai_response: str,
    job_id: str,
) -> None:
    """Store generation results in S3."""
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET not configured")

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
                [r for r in video_results if r.get("status") == "success"]
            ),
            "successful_audio": len(
                [r for r in audio_results if r.get("status") == "success"]
            ),
        }

        s3_key = f"combined-generations/{job_id}/results.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(job_summary, indent=2),
            ContentType="application/json",
        )
        logger.info(f"Stored results in S3: {s3_key}")

    except Exception as e:
        logger.error(f"Error storing results: {str(e)}")


def complete_job(job_id: str, video_type: str, ai_response: str) -> None:
    """Complete job and trigger next step."""
    try:
        if not JOB_COORDINATION_TABLE:
            return

        expires_at = int(time.time()) + (7 * 24 * 60 * 60)

        # Update job status
        dynamodb.update_item(
            TableName=JOB_COORDINATION_TABLE,
            Key={"job_id": {"S": job_id}},
            UpdateExpression="SET video_audio_status = :status, video_audio_updated_at = :timestamp, expires_at = :expires",
            ExpressionAttributeValues={
                ":status": {"S": "complete"},
                ":timestamp": {"N": str(int(time.time()))},
                ":expires": {"N": str(expires_at)},
            },
        )

        # Trigger next step
        trigger_next_step(job_id, video_type, ai_response)

    except Exception as e:
        logger.error(f"Error completing job: {str(e)}")


def trigger_next_step(job_id: str, video_type: str, ai_response: str) -> None:
    """Trigger composition or direct upload based on video type."""
    try:
        # Prepare response payload
        response_payload = {"job_id": job_id}
        if ai_response:
            try:
                response_data = (
                    json.loads(ai_response)
                    if isinstance(ai_response, str)
                    else ai_response
                )
                if "response" in response_data:
                    response_payload["response"] = response_data["response"]
                else:
                    response_payload["response"] = response_data
            except Exception as e:
                logger.warning(f"Failed to extract response payload: {str(e)}")

        if video_type == "short":
            # Direct YouTube upload for shorts
            function_name = os.environ.get("YOUTUBE_UPLOAD_FUNCTION_NAME")
            if function_name:
                response_payload["video_type"] = "short"
                lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType="Event",
                    Payload=json.dumps(response_payload),
                )
                logger.info(f"Triggered YouTube upload for shorts job {job_id}")
        else:
            # Composition for regular videos
            function_name = os.environ.get("COMPOSE_FUNCTION_NAME")
            if function_name:
                lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType="Event",
                    Payload=json.dumps(response_payload),
                )
                logger.info(f"Triggered composition for job {job_id}")

    except Exception as e:
        logger.error(f"Error triggering next step: {str(e)}")
