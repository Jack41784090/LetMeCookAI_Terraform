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
    execution_id = context.aws_request_id if context else "unknown"
    logger.info(f"Starting media generation lambda execution {execution_id}", extra={
        "execution_id": execution_id,
        "event_type": "sqs" if "Records" in event else "direct_invoke"
    })
    
    try:
        records = event.get("Records", [{"body": json.dumps(event)}])
        processed, failed = 0, 0
        
        logger.info(f"Processing {len(records)} record(s)", extra={
            "execution_id": execution_id,
            "record_count": len(records)
        })

        for idx, record in enumerate(records):
            try:
                message = json.loads(record["body"])
                logger.info(f"Processing record {idx + 1}/{len(records)}", extra={
                    "execution_id": execution_id,
                    "record_index": idx,
                    "message_keys": list(message.keys())
                })
                
                job_id = process_media_request(message)
                processed += 1
                logger.info(f"Successfully processed job: {job_id}", extra={
                    "execution_id": execution_id,
                    "job_id": job_id,
                    "record_index": idx
                })
            except Exception as e:
                logger.error(f"Failed to process record {idx + 1}: {str(e)}", extra={
                    "execution_id": execution_id,
                    "record_index": idx,
                    "error_type": type(e).__name__
                }, exc_info=True)
                failed += 1

        logger.info(f"Execution {execution_id} completed", extra={
            "execution_id": execution_id,
            "processed": processed,
            "failed": failed,
            "success_rate": f"{(processed/(processed+failed)*100):.1f}%" if (processed+failed) > 0 else "0%"
        })

        return {
            "statusCode": 200,
            "body": json.dumps({"processed": processed, "failed": failed}),
        }
    except Exception as e:
        logger.error(f"Lambda handler error in execution {execution_id}: {str(e)}", extra={
            "execution_id": execution_id,
            "error_type": type(e).__name__
        }, exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def process_media_request(message: Dict[str, Any]) -> str:
    """Process a single media generation request."""
    logger.info("Starting media request processing", extra={
        "message_keys": list(message.keys()),
        "message_size": len(str(message))
    })
    
    # Extract and validate required fields
    prompt = message.get("prompt", "")
    role = message.get("role", "")
    response = message.get("response", "")
    video_type = message.get("type", "")

    if not all([prompt, role, response, video_type]):
        missing_fields = [k for k, v in {"prompt": prompt, "role": role, "response": response, "type": video_type}.items() if not v]
        logger.error(f"Missing required fields: {missing_fields}")
        raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

    logger.info("Request parameters validated", extra={
        "video_type": video_type,
        "prompt_length": len(prompt),
        "role": role,
        "response_length": len(str(response))
    })

    # Extract scenes and generate job ID
    scenes = extract_scenes(response)
    if not scenes:
        logger.error("No scenes found in AI response")
        raise ValueError("No scenes found in AI response")

    job_id = f"job_{int(time.time())}_{hash(prompt) % 10000}"
    
    logger.info(f"Generated job ID: {job_id}", extra={
        "job_id": job_id,
        "scene_count": len(scenes),
        "video_type": video_type
    })

    # Initialize job coordination
    initialize_job(job_id, prompt, role, video_type, str(response))

    # Generate media
    try:
        # Parse response to extract master_prompt_context
        if isinstance(response, str):
            logger.debug("Parsing response string for master prompt context")
            cleaned_response = response.strip().replace("```json", "").replace("```", "")
            parsed_response = json.loads(cleaned_response)
        else:
            parsed_response = response
            
        master_prompt = parsed_response.get("master_prompt_context")
        if not master_prompt:
            logger.error("Master prompt context missing in response", extra={"job_id": job_id})
            raise ValueError("Master prompt context missing in response")
        master_positive_prompt = master_prompt.get("positive_prefix")
        if not master_positive_prompt:
            logger.error("Master positive prompt missing in response", extra={"job_id": job_id})
            raise ValueError("Master positive prompt missing in response")
    except (json.JSONDecodeError, AttributeError) as e:
        logger.error(f"Failed to parse response for master prompt context: {str(e)}", extra={
            "job_id": job_id,
            "error_type": type(e).__name__
        })
        raise ValueError(f"Invalid response format for master prompt extraction: {str(e)}")
    
    logger.info(f"Starting media generation for job {job_id}", extra={
        "job_id": job_id,
        "master_prompt_length": len(master_positive_prompt)
    })
    
    video_results, audio_results = asyncio.run(
        generate_media(scenes, job_id, video_type, master_positive_prompt)
    )

    # Store results and update status
    store_results(video_results, audio_results, prompt, role, str(response), job_id)
    complete_job(job_id, video_type, str(response))

    logger.info(f"Media request processing completed for job {job_id}", extra={
        "job_id": job_id,
        "video_results_count": len(video_results),
        "audio_results_count": len(audio_results)
    })

    return job_id


def extract_scenes(response) -> List[Dict[str, Any]]:
    """Extract scene descriptions from AI response."""
    logger.debug("Starting scene extraction from AI response")
    
    try:
        # Parse response if it's a string
        if isinstance(response, str):
            logger.debug("Parsing string response to JSON")
            # Clean markdown formatting
            cleaned = response.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(cleaned)
        else:
            logger.debug("Response is already parsed object")
            parsed = response

        # Extract scenes from structured format
        if isinstance(parsed, dict) and "scenes" in parsed:
            raw_scenes = parsed["scenes"]
            logger.info(f"Found {len(raw_scenes)} scenes in response")
            
            scenes = []
            for idx, scene in enumerate(raw_scenes):
                scene_data = {
                    "scene_number": scene.get("scene_number", idx + 1),
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
                scenes.append(scene_data)
                
                logger.debug(f"Extracted scene {idx + 1}", extra={
                    "scene_number": scene_data["scene_number"],
                    "duration": scene_data["duration"],
                    "has_voiceover": bool(scene_data["voiceover"]),
                    "visual_desc_length": len(scene_data["visual_description"])
                })
            
            logger.info(f"Successfully extracted {len(scenes)} scenes")
            return scenes
        else:
            logger.error("Response missing 'scenes' key", extra={
                "response_keys": list(parsed.keys()) if isinstance(parsed, dict) else "not_dict"
            })
            raise ValueError("Response missing 'scenes' key")

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Error extracting scenes: {str(e)}", extra={
            "error_type": type(e).__name__,
            "response_type": type(response).__name__
        })
        raise


async def generate_media(
    scenes: List[Dict[str, Any]], job_id: str, video_type: str, master_prompt: str
) -> tuple:
    """Generate video and audio for all scenes in parallel."""
    logger.info(f"Starting media generation for job: {job_id}", extra={
        "job_id": job_id,
        "scene_count": len(scenes),
        "video_type": video_type,
        "master_prompt_length": len(master_prompt)
    })

    # Create video generation tasks
    video_tasks = [
        generate_video(scene, i, job_id, video_type, master_prompt) for i, scene in enumerate(scenes)
    ]

    # For shorts, skip audio generation
    if video_type == "short":
        logger.info(f"Processing shorts - skipping audio generation for job {job_id}")
        start_time = time.time()
        video_results = await asyncio.gather(*video_tasks, return_exceptions=True)
        generation_time = time.time() - start_time
        
        logger.info(f"Video generation completed for job {job_id}", extra={
            "job_id": job_id,
            "generation_time_seconds": round(generation_time, 2),
            "video_count": len(video_results)
        })
        return process_results(video_results, scenes), []

    # For regular videos, generate both video and audio
    logger.info(f"Processing regular video - generating both video and audio for job {job_id}")
    audio_tasks = [generate_audio(scene, i, job_id) for i, scene in enumerate(scenes)]

    start_time = time.time()
    video_results, audio_results = await asyncio.gather(
        asyncio.gather(*video_tasks, return_exceptions=True),
        asyncio.gather(*audio_tasks, return_exceptions=True),
    )
    generation_time = time.time() - start_time
    
    logger.info(f"Media generation completed for job {job_id}", extra={
        "job_id": job_id,
        "generation_time_seconds": round(generation_time, 2),
        "video_count": len(video_results),
        "audio_count": len(audio_results)
    })

    return process_results(video_results, scenes), process_results(
        audio_results, scenes
    )


def process_results(
    results: List, scenes: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Process generation results and handle exceptions."""
    processed = []
    success_count = 0
    failure_count = 0
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failure_count += 1
            logger.error(f"Generation failed for scene {i+1}: {str(result)}", extra={
                "scene_index": i,
                "error_type": type(result).__name__
            })
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
            success_count += 1
            processed.append(result)
    
    logger.info(f"Result processing completed", extra={
        "total_scenes": len(results),
        "successful": success_count,
        "failed": failure_count,
        "success_rate": f"{(success_count/len(results)*100):.1f}%" if results else "0%"
    })
    
    return processed


async def generate_video(
    scene: Dict[str, Any], scene_index: int, job_id: str, video_type: str, master_prompt: str
) -> Dict[str, Any]:
    """Generate a single video asynchronously."""
    scene_number = scene.get("scene_number", scene_index + 1)
    
    logger.info(f"Starting video generation for scene {scene_number}", extra={
        "job_id": job_id,
        "scene_number": scene_number,
        "scene_index": scene_index,
        "video_type": video_type
    })
    
    try:
        visual_desc = scene.get("visual_description", "")
        start_time = time.time()

        # Prepare video request
        video_request = get_video_request(scene, video_type, master_prompt)
        
        logger.debug(f"Video request prepared for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "model": video_request.get("model"),
            "duration": video_request.get("duration"),
            "aspect_ratio": video_request.get("aspect_ratio")
        })

        # Generate video
        video_result = await call_video_api(video_request, job_id, scene_number)
        generation_time = time.time() - start_time
        
        is_success = video_result.get("success", False)
        
        logger.info(f"Video generation {'completed' if is_success else 'failed'} for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "generation_time_seconds": round(generation_time, 2),
            "success": is_success,
            "has_s3_url": bool(video_result.get("s3_url"))
        })

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "scene_description": visual_desc,
            "voiceover": scene.get("voiceover", ""),
            "duration": scene.get("duration"),
            "video_result": video_result,
            "status": "success" if is_success else "failed",
            "generation_time": round(generation_time, 2)
        }
    except Exception as e:
        logger.error(f"Video generation failed for scene {scene_number}: {str(e)}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "scene_index": scene_index,
            "error_type": type(e).__name__
        }, exc_info=True)
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
    scene_number = scene.get("scene_number", scene_index + 1)
    voiceover_text = scene.get("voiceover", "")
    
    logger.info(f"Starting audio generation for scene {scene_number}", extra={
        "job_id": job_id,
        "scene_number": scene_number,
        "scene_index": scene_index,
        "voiceover_length": len(voiceover_text)
    })
    
    try:
        if not voiceover_text.strip():
            logger.info(f"Skipping audio generation for scene {scene_number} - no voiceover text", extra={
                "job_id": job_id,
                "scene_number": scene_number
            })
            return {
                "scene_index": scene_index,
                "scene_number": scene_number,
                "status": "skipped",
                "message": "No voiceover text",
            }

        start_time = time.time()

        # Prepare audio request
        audio_request = {
            "prompt": voiceover_text,
            "voice": get_voice_setting(scene),
            "speed": get_speed_setting(scene),
        }
        
        logger.debug(f"Audio request prepared for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "voice": audio_request["voice"],
            "speed": audio_request["speed"],
            "text_length": len(voiceover_text)
        })

        # Generate audio
        audio_result = await call_audio_api(audio_request, job_id, scene_number)
        generation_time = time.time() - start_time
        
        is_success = audio_result.get("success", False)
        
        logger.info(f"Audio generation {'completed' if is_success else 'failed'} for scene {scene_number}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "generation_time_seconds": round(generation_time, 2),
            "success": is_success,
            "has_s3_url": bool(audio_result.get("s3_url"))
        })

        return {
            "scene_index": scene_index,
            "scene_number": scene_number,
            "voiceover_text": voiceover_text,
            "audio_result": audio_result,
            "status": "success" if is_success else "failed",
            "generation_time": round(generation_time, 2)
        }
    except Exception as e:
        logger.error(f"Audio generation failed for scene {scene_number}: {str(e)}", extra={
            "job_id": job_id,
            "scene_number": scene_number,
            "scene_index": scene_index,
            "error_type": type(e).__name__
        }, exc_info=True)
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
                logger.info(f"Triggered YouTube upload for shorts job {job_id}", extra={
                    "job_id": job_id,
                    "function_name": function_name
                })
            else:
                logger.warning(f"YOUTUBE_UPLOAD_FUNCTION_NAME not configured - cannot trigger upload for job {job_id}")
        else:
            # Composition for regular videos
            function_name = os.environ.get("COMPOSE_FUNCTION_NAME")
            if function_name:
                lambda_client.invoke(
                    FunctionName=function_name,
                    InvocationType="Event",
                    Payload=json.dumps(response_payload),
                )
                logger.info(f"Triggered composition for job {job_id}", extra={
                    "job_id": job_id,
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
