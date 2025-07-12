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

# Simple logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

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
    execution_id = context.aws_request_id if context else "unknown"
    logger.info(f"Starting execution {execution_id}")
    
    try:
        records = event.get("Records", [{"body": json.dumps(event)}])
        processed, failed = 0, 0
        
        for idx, record in enumerate(records):
            try:
                message = json.loads(record["body"])
                job_id = process_media_request(message)
                processed += 1
                logger.info(f"Successfully processed job: {job_id}")
            except Exception as e:
                logger.error(f"Failed to process record {idx + 1}: {str(e)}")
                failed += 1

        logger.info(f"Execution completed - processed: {processed}, failed: {failed}")
        return {
            "statusCode": 200,
            "body": json.dumps({"processed": processed, "failed": failed}),
        }
    except Exception as e:
        logger.error(f"Lambda handler error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def process_media_request(message: Dict[str, Any]) -> str:
    """Process a single media generation request."""
    # Validate required fields
    prompt = message.get("prompt", "")
    role = message.get("role", "")
    response = message.get("response", "")
    video_type = message.get("type", "")

    if not all([prompt, role, response, video_type]):
        missing = [k for k, v in {"prompt": prompt, "role": role, "response": response, "type": video_type}.items() if not v]
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    # Extract scenes and generate job ID
    scenes = extract_scenes(response)
    if not scenes:
        raise ValueError("No scenes found in AI response")

    job_id = f"job_{int(time.time())}_{hash(prompt) % 10000}"
    logger.info(f"Processing job {job_id} with {len(scenes)} scenes")

    # Initialize job coordination
    initialize_job(job_id, prompt, role, video_type, str(response))

    # Extract master prompt
    master_prompt = get_master_prompt(response)
    
    # Generate media
    video_results, audio_results = asyncio.run(
        generate_media(scenes, job_id, video_type, master_prompt)
    )

    # Store results and complete job
    store_results(video_results, audio_results, prompt, role, str(response), job_id)
    complete_job(job_id, video_type, str(response))

    return job_id


def extract_scenes(response) -> List[Dict[str, Any]]:
    """Extract scene descriptions from AI response."""
    try:
        # Parse response if it's a string
        if isinstance(response, str):
            cleaned = response.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned)
        else:
            parsed = response

        # Extract scenes
        if isinstance(parsed, dict) and "scenes" in parsed:
            raw_scenes = parsed["scenes"]
            scenes = []
            
            for idx, scene in enumerate(raw_scenes):
                scene_data = {
                    "scene_number": scene.get("scene_number", idx + 1),
                    "duration": scene.get("duration_seconds", 10),
                    "visual_description": scene.get("visual_description", ""),
                    "voiceover": scene.get("voiceover", ""),
                    "positive_prompt": scene.get("positive_prompt", scene.get("visual_description", "")),
                    "negative_prompt": scene.get("negative_prompt", ""),
                    "master_prompt_context": parsed.get("master_prompt_context", {}),
                }
                scenes.append(scene_data)
            
            return scenes
        else:
            raise ValueError("Response missing 'scenes' key")

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error extracting scenes: {str(e)}")
        raise


def get_master_prompt(response) -> str:
    """Extract master prompt from response."""
    try:
        if isinstance(response, str):
            cleaned = response.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned)
        else:
            parsed = response
            
        master_prompt = parsed.get("master_prompt_context", {}).get("positive_prefix", "")
        if not master_prompt:
            raise ValueError("Master positive prompt missing")
        return master_prompt
    except Exception as e:
        logger.error(f"Failed to extract master prompt: {str(e)}")
        raise


async def generate_media(scenes: List[Dict[str, Any]], job_id: str, video_type: str, master_prompt: str) -> tuple:
    """Generate video and audio for all scenes in parallel."""
    logger.info(f"Starting media generation for job {job_id}")

    # Create video tasks
    video_tasks = [generate_video(scene, i, job_id, video_type, master_prompt) for i, scene in enumerate(scenes)]

    # Skip audio for shorts
    if video_type == "short":
        video_results = await asyncio.gather(*video_tasks, return_exceptions=True)
        return process_results(video_results, scenes), []

    # Generate both video and audio for regular videos
    audio_tasks = [generate_audio(scene, i, job_id) for i, scene in enumerate(scenes)]
    video_results, audio_results = await asyncio.gather(
        asyncio.gather(*video_tasks, return_exceptions=True),
        asyncio.gather(*audio_tasks, return_exceptions=True),
    )

    return process_results(video_results, scenes), process_results(audio_results, scenes)


def process_results(results: List, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process generation results and handle exceptions."""
    processed = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Generation failed for scene {i+1}: {str(result)}")
            processed.append({
                "scene_index": i,
                "scene_number": scenes[i].get("scene_number", i + 1),
                "status": "failed",
                "error": str(result),
            })
        else:
            processed.append(result)
    return processed


async def generate_video(scene: Dict[str, Any], scene_index: int, job_id: str, video_type: str, master_prompt: str) -> Dict[str, Any]:
    """Generate a single video asynchronously."""
    scene_number = scene.get("scene_number", scene_index + 1)
    
    try:
        video_request = get_video_request(scene, video_type, master_prompt)
        video_result = await call_video_api(video_request, job_id, scene_number)
        
        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "scene_description": scene.get("visual_description", ""),
            "voiceover": scene.get("voiceover", ""),
            "duration": scene.get("duration"),
            "video_result": video_result,
            "status": "success" if video_result.get("success") else "failed",
        }
    except Exception as e:
        logger.error(f"Video generation failed for scene {scene_number}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "status": "failed",
            "error": str(e),
        }


async def generate_audio(scene: Dict[str, Any], scene_index: int, job_id: str) -> Dict[str, Any]:
    """Generate a single audio track asynchronously."""
    scene_number = scene.get("scene_number", scene_index + 1)
    voiceover_text = scene.get("voiceover", "")
    
    try:
        if not voiceover_text.strip():
            return {
                "scene_index": scene_index,
                "scene_number": scene_number,
                "status": "skipped",
                "message": "No voiceover text",
            }

        audio_request = {
            "prompt": voiceover_text,
            "voice": get_voice_setting(scene),
            "speed": get_speed_setting(scene),
        }
        
        audio_result = await call_audio_api(audio_request, job_id, scene_number)
        
        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "voiceover_text": voiceover_text,
            "audio_result": audio_result,
            "status": "success" if audio_result.get("success") else "failed",
        }
    except Exception as e:
        logger.error(f"Audio generation failed for scene {scene_number}: {str(e)}")
        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
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
    logger.info(f"Calling video API for scene {scene_number}", extra={
        "job_id": job_id,
        "scene_number": scene_number,
        "model": video_request.get("model"),
        "duration": video_request.get("duration")
    })
    
    try:
        if not FAL_KEY:
            logger.error("FAL API key not configured", extra={
                "job_id": job_id,
                "scene_number": scene_number
            })
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY
        api_start_time = time.time()

        # Submit async request
        handler = await fal_client.submit_async(
            video_request["model"],
            arguments={k: v for k, v in video_request.items() if k != "model"},
        )

        # Get result
        result = await handler.get()
        api_time = time.time() - api_start_time
        
        logger.info(f"Video API response received for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "api_time_seconds": round(api_time, 2),
            "has_video_url": bool(result and "video" in result and "url" in result.get("video", {}))
        })

        if result and "video" in result and "url" in result["video"]:
            video_url = result["video"]["url"]
            s3_key = f"generated-videos/{job_id}/scene_{scene_number:02d}.mp4"
            
            logger.info(f"Starting S3 upload for scene {scene_number}", extra={
                "job_id": job_id,
                "scene_number": scene_number,
                "s3_key": s3_key
            })
            
            download_result = download_to_s3(video_url, s3_key, "video/mp4")

            return {"original_video_url": video_url, "success": True, **download_result}
        else:
            logger.error(f"Invalid video API response for scene {scene_number}", extra={
                "job_id": job_id,
                "scene_number": scene_number,
                "result_keys": list(result.keys()) if result else None
            })
            return {"error": "No video URL in response", "details": result}

    except Exception as e:
        logger.error(f"Video API error for scene {scene_number}: {str(e)}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "error_type": type(e).__name__
        }, exc_info=True)
        return {"error": "API call failed", "details": str(e)}


async def call_audio_api(
    audio_request: Dict[str, Any], job_id: str, scene_number: int
) -> Dict[str, Any]:
    """Call audio generation API."""
    logger.info(f"Calling audio API for scene {scene_number}", extra={
        "job_id": job_id,
        "scene_number": scene_number,
        "voice": audio_request.get("voice"),
        "speed": audio_request.get("speed"),
        "text_length": len(audio_request.get("prompt", ""))
    })
    
    try:
        if not FAL_KEY:
            logger.error("FAL API key not configured", extra={
                "job_id": job_id,
                "scene_number": scene_number
            })
            return {"error": "FAL API key not configured"}

        os.environ["FAL_KEY"] = FAL_KEY
        api_start_time = time.time()

        # Submit async request
        handler = await fal_client.submit_async(
            "fal-ai/kokoro/hindi", arguments=audio_request
        )

        # Get result
        result = await handler.get()
        api_time = time.time() - api_start_time
        
        logger.info(f"Audio API response received for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "api_time_seconds": round(api_time, 2),
            "has_audio_url": bool(result and "audio" in result and "url" in result.get("audio", {}))
        })

        if result and "audio" in result and "url" in result["audio"]:
            audio_url = result["audio"]["url"]
            s3_key = f"generated-audio/{job_id}/scene_{scene_number:02d}.wav"
            
            logger.info(f"Starting S3 upload for audio scene {scene_number}", extra={
                "job_id": job_id,
                "scene_number": scene_number,
                "s3_key": s3_key
            })
            
            download_result = download_to_s3(audio_url, s3_key, "audio/wav")

            return {"original_audio_url": audio_url, "success": True, **download_result}
        else:
            logger.error(f"Invalid audio API response for scene {scene_number}", extra={
                "job_id": job_id,
                "scene_number": scene_number,
                "result_keys": list(result.keys()) if result else None
            })
            return {"error": "No audio URL in response", "details": result}

    except Exception as e:
        logger.error(f"Audio API error for scene {scene_number}: {str(e)}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "error_type": type(e).__name__
        }, exc_info=True)
        return {"error": "API call failed", "details": str(e)}


def download_to_s3(url: str, s3_key: str, content_type: str) -> Dict[str, Any]:
    """Download file from URL and store in S3."""
    logger.info(f"Starting download to S3", extra={
        "s3_key": s3_key,
        "content_type": content_type,
        "url_domain": urlparse(url).netloc
    })
    
    try:
        if not S3_BUCKET:
            logger.error("S3_BUCKET not configured")
            return {"success": False, "error": "S3_BUCKET not configured"}

        download_start = time.time()
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        download_time = time.time() - download_start
        
        file_size = int(response.headers.get('content-length', 0))
        logger.info(f"File downloaded successfully", extra={
            "s3_key": s3_key,
            "file_size_mb": round(file_size / (1024*1024), 2) if file_size else "unknown",
            "download_time_seconds": round(download_time, 2)
        })

        upload_start = time.time()
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
        upload_time = time.time() - upload_start

        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        logger.info(f"Successfully uploaded to S3: {s3_url}", extra={
            "s3_key": s3_key,
            "s3_url": s3_url,
            "upload_time_seconds": round(upload_time, 2),
            "total_time_seconds": round(download_time + upload_time, 2)
        })

        return {
            "success": True,
            "s3_key": s3_key,
            "s3_url": s3_url,
            "stored_in_s3": True,
            "file_size_mb": round(file_size / (1024*1024), 2) if file_size else None
        }

    except Exception as e:
        logger.error(f"S3 upload error: {str(e)}", extra={
            "s3_key": s3_key,
            "error_type": type(e).__name__
        }, exc_info=True)
        return {"success": False, "error": str(e)}


def initialize_job(
    job_id: str, prompt: str, role: str, video_type: str, ai_response: str
) -> None:
    """Initialize job coordination record."""
    logger.info(f"Initializing job coordination for {job_id}", extra={
        "job_id": job_id,
        "video_type": video_type,
        "table_name": JOB_COORDINATION_TABLE or "NOT_CONFIGURED"
    })
    
    try:
        if not JOB_COORDINATION_TABLE:
            logger.warning("No coordination table specified - skipping job initialization")
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
                # Handle both string and dict types for ai_response
                if isinstance(ai_response, str):
                    # Clean and parse JSON string
                    cleaned_response = ai_response.strip().replace("```json", "").replace("```", "")
                    if cleaned_response:  # Only parse if not empty
                        response_data = json.loads(cleaned_response)
                    else:
                        logger.warning(f"Empty AI response string for job {job_id}")
                        response_data = {}
                else:
                    response_data = ai_response
                
                # Extract metadata from response structure
                response_obj = response_data.get("response", response_data) if isinstance(response_data, dict) else {}

                metadata_fields = ["title", "summary", "topic"]
                extracted_fields = []
                
                for field in metadata_fields:
                    if isinstance(response_obj, dict) and field in response_obj:
                        item[f"video_{field}"] = {"S": str(response_obj[field])}
                        extracted_fields.append(field)

                if isinstance(response_obj, dict) and "hashtags" in response_obj and isinstance(
                    response_obj["hashtags"], list
                ):
                    item["video_hashtags"] = {"S": ",".join(str(tag) for tag in response_obj["hashtags"])}
                    extracted_fields.append("hashtags")

                # Store the full AI response
                item["ai_response"] = {
                    "S": ai_response if isinstance(ai_response, str) else json.dumps(ai_response)
                }

                logger.debug(f"Extracted metadata for job {job_id}", extra={
                    "job_id": job_id,
                    "extracted_fields": extracted_fields,
                    "response_type": type(response_data).__name__
                })

            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                logger.warning(f"Failed to extract video metadata for job {job_id}: {str(e)}", extra={
                    "job_id": job_id,
                    "error_type": type(e).__name__,
                    "ai_response_type": type(ai_response).__name__
                })
                # Still store the raw response even if parsing fails
                item["ai_response"] = {
                    "S": ai_response if isinstance(ai_response, str) else str(ai_response)
                }

        try:
            dynamodb.put_item(TableName=JOB_COORDINATION_TABLE, Item=item)
            logger.info(f"Job coordination initialized successfully for {job_id}")
        except Exception as db_error:
            logger.error(f"DynamoDB put_item failed for job {job_id}: {str(db_error)}", extra={
                "job_id": job_id,
                "error_type": type(db_error).__name__,
                "table_name": JOB_COORDINATION_TABLE
            })
            # Don't re-raise this error to allow processing to continue
            logger.warning(f"Continuing without job coordination for {job_id}")

    except Exception as e:
        logger.error(f"Error initializing job coordination for {job_id}: {str(e)}", extra={
            "job_id": job_id,
            "error_type": type(e).__name__,
            "table_configured": bool(JOB_COORDINATION_TABLE)
        }, exc_info=True)
        # Don't re-raise to allow processing to continue without job coordination


def store_results(
    video_results: List[Dict[str, Any]],
    audio_results: List[Dict[str, Any]],
    prompt: str,
    role: str,
    ai_response: str,
    job_id: str,
) -> None:
    """Store generation results in S3."""
    logger.info(f"Storing results for job {job_id}", extra={
        "job_id": job_id,
        "video_results_count": len(video_results),
        "audio_results_count": len(audio_results),
        "s3_bucket": S3_BUCKET or "NOT_CONFIGURED"
    })
    
    try:
        if not S3_BUCKET:
            logger.error(f"S3_BUCKET not configured - cannot store results for job {job_id}")
            raise ValueError("S3_BUCKET not configured")

        successful_videos = len([r for r in video_results if r.get("status") == "success"])
        successful_audio = len([r for r in audio_results if r.get("status") == "success"])

        job_summary = {
            "job_id": job_id,
            "timestamp": int(time.time()),
            "original_prompt": prompt,
            "role": role,
            "ai_response": ai_response,
            "total_scenes": len(video_results),
            "video_results": video_results,
            "audio_results": audio_results,
            "successful_videos": successful_videos,
            "successful_audio": successful_audio,
            "success_rates": {
                "video": f"{(successful_videos/len(video_results)*100):.1f}%" if video_results else "0%",
                "audio": f"{(successful_audio/len(audio_results)*100):.1f}%" if audio_results else "0%"
            }
        }

        s3_key = f"combined-generations/{job_id}/results.json"
        
        upload_start = time.time()
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(job_summary, indent=2),
            ContentType="application/json",
        )
        upload_time = time.time() - upload_start
        
        logger.info(f"Results stored successfully for job {job_id}", extra={
            "job_id": job_id,
            "s3_key": s3_key,
            "upload_time_seconds": round(upload_time, 2),
            "successful_videos": successful_videos,
            "successful_audio": successful_audio
        })

    except Exception as e:
        logger.error(f"Error storing results for job {job_id}: {str(e)}", extra={
            "job_id": job_id,
            "error_type": type(e).__name__
        }, exc_info=True)


def complete_job(job_id: str, video_type: str, ai_response: str) -> None:
    """Complete job and trigger next step."""
    logger.info(f"Completing job {job_id}", extra={
        "job_id": job_id,
        "video_type": video_type,
        "table_name": JOB_COORDINATION_TABLE or "NOT_CONFIGURED"
    })
    
    try:
        if not JOB_COORDINATION_TABLE:
            logger.warning(f"No coordination table configured - skipping job completion for {job_id}")
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
        
        logger.info(f"Job status updated to complete for {job_id}")

        # Trigger next step
        trigger_next_step(job_id, video_type, ai_response)

    except Exception as e:
        logger.error(f"Error completing job {job_id}: {str(e)}", extra={
            "job_id": job_id,
            "error_type": type(e).__name__
        }, exc_info=True)


def trigger_next_step(job_id: str, video_type: str, ai_response: str) -> None:
    """Trigger composition or direct upload based on video type."""
    logger.info(f"Triggering next step for job {job_id}", extra={
        "job_id": job_id,
        "video_type": video_type,
        "next_step": "youtube_upload" if video_type == "short" else "composition"
    })
    
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
                    
                logger.debug(f"Response payload prepared for job {job_id}")
            except Exception as e:
                logger.warning(f"Failed to extract response payload for job {job_id}: {str(e)}")

        # Trigger composition for both regular videos and shorts
        function_name = os.environ.get("COMPOSE_FUNCTION_NAME")
        if function_name:
            response_payload["video_type"] = video_type
            lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="Event",
                Payload=json.dumps(response_payload),
            )
            logger.info(f"Triggered composition for {video_type} job {job_id}", extra={
                "job_id": job_id,
                "video_type": video_type,
                "function_name": function_name
            })
        else:
            logger.warning(f"COMPOSE_FUNCTION_NAME not configured - cannot trigger composition for job {job_id}")

    except Exception as e:
        logger.error(f"Error triggering next step for job {job_id}: {str(e)}", extra={
            "job_id": job_id,
            "video_type": video_type,
            "error_type": type(e).__name__
        }, exc_info=True)
