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

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sqs = boto3.client('sqs', region_name='us-east-2')
s3 = boto3.client('s3', region_name='us-east-2')
dynamodb = boto3.client('dynamodb', region_name='us-east-2')

# Environment variables
SQS_QUEUE_URL = os.environ.get('SQS_QUEUE_URL')
S3_BUCKET = os.environ.get('S3_BUCKET')
FAL_KEY = os.environ.get('FAL_KEY')  # FAL API key for audio generation

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to process audio generation requests from SQS messages.
    
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
        if 'Records' in event:
            # Process SQS records
            logger.info(f"Processing {len(event['Records'])} SQS records")
            records_to_process = event['Records']
        else:
            # Direct event for testing - wrap it as a single record
            logger.info("Processing direct event (test mode)")
            records_to_process = [{'body': json.dumps(event)}]
        
        # Process each record
        for record in records_to_process:
            try:
                # Parse the SQS message body
                message_body = json.loads(record['body'])
                logger.info(f"Processing message: {message_body}")
                
                # Extract data from the message
                prompt = message_body.get('prompt')
                role = message_body.get('role') 
                response = message_body.get('response')
                
                if not all([prompt, role, response]):
                    logger.error("Missing required fields in message")
                    failed_count += 1
                    continue
                
                # Parse the AI response to extract scenes
                scenes = extract_scenes_from_response(response)
                
                if not scenes:
                    logger.error("No scenes found in AI response")
                    failed_count += 1
                    continue
                
                # Generate audio for each scene
                audio_results = generate_audio_for_scenes(scenes, prompt, role)
                
                # Store results
                store_audio_results(audio_results, prompt, role, response)
                
                processed_count += 1
                logger.info(f"Successfully processed message with {len(scenes)} scenes")
                
            except Exception as e:
                logger.error(f"Error processing SQS record: {str(e)}")
                failed_count += 1
                continue
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Processed {processed_count} messages successfully, {failed_count} failed',
                'processed': processed_count,
                'failed': failed_count
            })
        }
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }

def extract_scenes_from_response(response) -> List[Dict[str, Any]]:
    """
    Extract scene descriptions from the AI response.
    
    Args:
        response: AI response containing scene descriptions (JSON format expected)
        
    Returns:
        List of scene dictionaries with voiceover text and metadata
    """
    scenes = []
    
    try:
        # Parse the JSON response from the AI
        if isinstance(response, dict):
            # Response is already a dictionary (direct test event)
            parsed_response = response
        else:
            # Response is a JSON string (from SQS)
            parsed_response = json.loads(response)
        
        # Handle structured video script format
        if isinstance(parsed_response, dict) and 'scenes' in parsed_response:
            video_scenes = parsed_response['scenes']
            for scene in video_scenes:
                scene_data = {
                    'scene_number': scene.get('scene_number', 1),
                    'duration': scene.get('duration_seconds', 10),
                    'visual_description': scene.get('visual_description', ''),
                    'voiceover': scene.get('voiceover', ''),
                    'positive_prompt': scene.get('positive_prompt', scene.get('visual_description', '')),
                    'negative_prompt': scene.get('negative_prompt', ''),
                    'topic': parsed_response.get('topic', 'Unknown'),
                    'title': parsed_response.get('title', 'Unknown'),
                    'master_prompt_context': parsed_response.get('master_prompt_context', {})
                }
                scenes.append(scene_data)
            
            logger.info(f"Extracted {len(scenes)} structured scenes from video script JSON")
            return scenes
        
        # Handle simple list format
        elif isinstance(parsed_response, list):
            return [{'voiceover': scene, 'duration': 10} for scene in parsed_response]
        
        # Handle simple dict without scenes key
        elif isinstance(parsed_response, dict):
            # Try to find scene-like content in the dict
            for key, value in parsed_response.items():
                if 'scene' in key.lower() and isinstance(value, list):
                    return [{'voiceover': scene, 'duration': 10} for scene in value]
        
    except json.JSONDecodeError:
        logger.warning("Response is not valid JSON, attempting text parsing")
        
        # Only do text parsing if response is a string
        if isinstance(response, str):
            # Fallback to text parsing for non-JSON responses
            scene_patterns = [
                r'Scene \d+[:\-]\s*(.+?)(?=Scene \d+|$)',
                r'\d+\.\s*(.+?)(?=\d+\.|$)',
                r'- (.+?)(?=\n-|$)',
            ]
            
            for pattern in scene_patterns:
                matches = re.findall(pattern, response, re.MULTILINE | re.DOTALL)
                if matches:
                    scenes = [{'voiceover': match.strip(), 'duration': 10} for match in matches if match.strip()]
                    break
            
            # If no structured scenes found, split by sentences or paragraphs
            if not scenes:
                paragraphs = [p.strip() for p in response.split('\n\n') if p.strip()]
                if len(paragraphs) > 1:
                    scenes = [{'voiceover': para, 'duration': 10} for para in paragraphs]
                else:
                    sentences = [s.strip() for s in response.split('.') if s.strip() and len(s.strip()) > 20]
                    scenes = [{'voiceover': sentence + '.', 'duration': 8} for sentence in sentences[:5]]
            
            logger.info(f"Extracted {len(scenes)} scenes from text parsing")
        
    except Exception as e:
        logger.error(f"Error extracting scenes: {str(e)}")
    
    # Return scenes (empty list if nothing found)
    return scenes

def generate_audio_for_scenes(scenes: List[Dict[str, Any]], original_prompt: str, role: str) -> List[Dict[str, Any]]:
    """
    Generate audio for each scene using external API.
    
    Args:
        scenes: List of scene descriptions with structured data
        original_prompt: Original user prompt for context
        role: AI role used for context
        
    Returns:
        List of audio generation results
    """
    audio_results = []
    
    # Generate unique job ID for this audio generation batch
    job_id = f"audio_job_{int(time.time())}_{hash(original_prompt) % 10000}"
    
    for i, scene in enumerate(scenes):
        try:
            # Get voiceover text - handle both structured and simple formats
            if 'voiceover' in scene:
                voiceover_text = scene['voiceover']
                scene_number = scene.get('scene_number', i + 1)
                duration = scene.get('duration', 10)
                visual_desc = scene.get('visual_description', '')
                
                logger.info(f"Generating audio for scene {scene_number}: {voiceover_text[:100]}...")
            else:
                voiceover_text = scene.get('description', '')
                scene_number = i + 1
                duration = scene.get('duration', 10)
                visual_desc = voiceover_text
                
                logger.info(f"Generating audio for scene {scene_number}: {voiceover_text[:100]}...")
            
            # Skip if no voiceover text
            if not voiceover_text.strip():
                logger.warning(f"No voiceover text for scene {scene_number}, skipping")
                audio_results.append({
                    'scene_index': i,
                    'scene_number': scene_number,
                    'voiceover_text': '',
                    'visual_description': visual_desc,
                    'duration': duration,
                    'audio_result': None,
                    'status': 'skipped',
                    'message': 'No voiceover text provided'
                })
                continue
              # Prepare the audio generation request for Hindi TTS
            audio_request = {
                'prompt': voiceover_text,
                'voice': 'hf_alpha',  # Default Hindi female voice
                'speed': 1.0
            }
              # Add master prompt context if available for voice selection
            if 'master_prompt_context' in scene:
                master_context = scene['master_prompt_context']
                if master_context.get('voice_style'):
                    # Map voice styles to Hindi voices
                    voice_mapping = {
                        'female_alpha': 'hf_alpha',
                        'female_beta': 'hf_beta', 
                        'male_omega': 'hm_omega',
                        'male_psi': 'hm_psi'
                    }
                    audio_request['voice'] = voice_mapping.get(master_context['voice_style'], 'hf_alpha')
                if master_context.get('speech_speed'):
                    audio_request['speed'] = master_context['speech_speed']
            
            # Make request to external audio generation API
            audio_result = call_audio_generation_api(audio_request, job_id, scene_number)
            
            audio_results.append({
                'scene_index': i,
                'scene_number': scene_number,
                'voiceover_text': voiceover_text,
                'visual_description': visual_desc,
                'duration': duration,
                'audio_request': audio_request,
                'audio_result': audio_result,
                'status': 'success' if audio_result.get('audio') else 'failed'
            })
            
            # Add delay between requests to respect API rate limits
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Error generating audio for scene {i+1}: {str(e)}")
            audio_results.append({
                'scene_index': i,
                'scene_number': scene.get('scene_number', i + 1),
                'voiceover_text': scene.get('voiceover', scene.get('description', '')),
                'visual_description': scene.get('visual_description', ''),
                'duration': scene.get('duration', 10),
                'audio_result': None,
                'status': 'failed',
                'error': str(e)
            })
    
    return audio_results

def download_audio_to_s3(audio_url: str, s3_key: str) -> Dict[str, Any]:
    """
    Download audio from URL and store it in S3.
    
    Args:
        audio_url: URL of the audio to download
        s3_key: S3 key where the audio will be stored
        
    Returns:
        Dictionary with download status and S3 location
    """
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")
        
        logger.info(f"Downloading audio from: {audio_url}")
        
        # Download the audio with streaming
        response = requests.get(audio_url, stream=True, timeout=300)
        response.raise_for_status()
          # Get content type from response headers
        content_type = response.headers.get('content-type', 'audio/wav')
        content_length = response.headers.get('content-length')
        
        logger.info(f"Audio size: {content_length} bytes, Content-Type: {content_type}")
        
        # Upload directly to S3 using streaming
        s3.upload_fileobj(
            response.raw,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                'ContentType': content_type,
                'Metadata': {
                    'source_url': audio_url,
                    'download_timestamp': str(int(time.time()))
                }
            }
        )
        
        # Generate S3 URL
        s3_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
        
        logger.info(f"Audio successfully uploaded to S3: {s3_url}")
        
        return {
            'success': True,
            's3_key': s3_key,
            's3_url': s3_url,
            'content_type': content_type,
            'size_bytes': content_length
        }
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading audio from {audio_url}: {str(e)}")
        return {
            'success': False,
            'error': f'Download failed: {str(e)}'
        }
    except Exception as e:
        logger.error(f"Error uploading audio to S3: {str(e)}")
        return {
            'success': False,
            'error': f'S3 upload failed: {str(e)}'
        }

def call_audio_generation_api(audio_request: Dict[str, Any], job_id: str, scene_number: int) -> Dict[str, Any]:
    """
    Call FAL audio generation API for text-to-speech.
    
    Args:
        audio_request: Audio generation parameters
        job_id: Unique identifier for this audio generation job
        scene_number: Scene number within the job
        
    Returns:
        API response with audio URL or error
    """
    try:
        if not FAL_KEY:
            logger.error("FAL_KEY environment variable not set")
            return {'error': 'FAL API key not configured'}
          # Set up FAL client with API key
        os.environ['FAL_KEY'] = FAL_KEY
        
        logger.info(f"Submitting audio generation request: {audio_request}")
        
        def on_queue_update(update):
            if isinstance(update, fal_client.InProgress):
                for log in update.logs:
                    logger.info(f"FAL Queue Update: {log.get('message', '')}")
        
        # # Submit request to FAL Kokoro Hindi TTS API
        # result = fal_client.subscribe(
        #     "fal-ai/kokoro/hindi",
        #     arguments=audio_request,
        #     with_logs=True,
        #     on_queue_update=on_queue_update,
        # )
        
        # For testing purposes, uncomment the lines below and comment out the actual API call above
        time.sleep(1)
        result = {
            'audio': {
                'url': 'https://fal-api-audio-uploads.s3.amazonaws.com/166db034-7421-4767-adad-ab7c36a99b75.mp3'
            }
        }
        
        logger.info(f"Audio generation successful: {result}")
        
        # Extract audio URL from result
        if result and 'audio' in result and 'url' in result['audio']:
            audio_url = result['audio']['url']
              # Generate S3 key with job_id folder structure
            parsed_url = urlparse(audio_url)
            filename = os.path.basename(parsed_url.path) or f"scene_{scene_number:02d}.wav"
            # Ensure filename includes scene number for easy ordering
            if not filename.startswith(f"scene_{scene_number:02d}"):
                name, ext = os.path.splitext(filename)
                if not ext:  # If no extension, default to .wav for Hindi TTS
                    ext = '.wav'
                filename = f"scene_{scene_number:02d}_{name}{ext}"
            
            s3_key = f"generated-audio/{job_id}/{filename}"
              # Download and store the audio in S3
            download_result = download_audio_to_s3(audio_url, s3_key)
            
            response_data = {
                'original_audio_url': audio_url,
                'file_size': result['audio'].get('file_size'),
                'content_type': result['audio'].get('content_type', 'audio/wav'),
                'success': True
            }
            
            # Add S3 information if download was successful
            if download_result['success']:
                response_data.update({
                    's3_key': download_result['s3_key'],
                    's3_url': download_result['s3_url'],
                    'stored_in_s3': True,
                    'download_size_bytes': download_result.get('size_bytes')
                })
            else:
                response_data.update({
                    'stored_in_s3': False,
                    'download_error': download_result['error']
                })
                logger.warning(f"Audio generated but download failed: {download_result['error']}")
            
            return response_data
        else:
            logger.error(f"No audio URL in result: {result}")
            return {'error': 'No audio URL in response', 'details': result}
            
    except Exception as e:
        logger.error(f"Error calling FAL audio API: {str(e)}")
        return {'error': 'API call failed', 'details': str(e)}

def store_audio_results(audio_results: List[Dict[str, Any]], prompt: str, role: str, ai_response: str) -> None:
    """
    Store audio generation results in S3.
    
    Args:
        audio_results: List of audio generation results
        prompt: Original prompt
        role: AI role
        ai_response: AI response containing scenes
    """
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")
        
        # Create a summary of the audio generation job
        job_summary = {
            'timestamp': int(time.time()),
            'original_prompt': prompt,
            'role': role,
            'ai_response': ai_response,
            'total_scenes': len(audio_results),
            'successful_audio': len([r for r in audio_results if r['status'] == 'success']),
            'failed_audio': len([r for r in audio_results if r['status'] == 'failed']),
            'skipped_audio': len([r for r in audio_results if r['status'] == 'skipped']),
            'audio_results': audio_results
        }
        
        # Store in S3 as JSON
        s3_key = f"audio-generations/{int(time.time())}-{hash(prompt) % 10000}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(job_summary, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Stored audio results in S3: {s3_key}")
            
    except Exception as e:
        logger.error(f"Error storing audio results: {str(e)}")
