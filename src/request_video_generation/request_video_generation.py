import json
import os
import boto3
import logging
import fal_client
import time
from typing import Any, Dict, List
import re

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
# JOB_STATUS_TABLE = os.environ.get('JOB_STATUS_TABLE')
FAL_KEY = os.environ.get('FAL_KEY')  # FAL API key for Bytedance Seedance

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to process video generation requests from SQS messages.
    
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
                
                # Generate videos for each scene
                video_results = generate_videos_for_scenes(scenes, prompt, role)
                
                # Store results (you might want to save to DynamoDB or S3)
                store_video_results(video_results, prompt, role, response)
                
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
        List of scene dictionaries with description and metadata
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
            return [{'description': scene, 'duration': 10} for scene in parsed_response]
          # Handle simple dict without scenes key
        elif isinstance(parsed_response, dict):
            # Try to find scene-like content in the dict
            for key, value in parsed_response.items():
                if 'scene' in key.lower() and isinstance(value, list):
                    return [{'description': scene, 'duration': 10} for scene in value]
        
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
                    scenes = [{'description': match.strip(), 'duration': 10} for match in matches if match.strip()]
                    break
            
            # If no structured scenes found, split by sentences or paragraphs
            if not scenes:
                paragraphs = [p.strip() for p in response.split('\n\n') if p.strip()]
                if len(paragraphs) > 1:
                    scenes = [{'description': para, 'duration': 10} for para in paragraphs]
                else:
                    sentences = [s.strip() for s in response.split('.') if s.strip() and len(s.strip()) > 20]
                    scenes = [{'description': sentence + '.', 'duration': 8} for sentence in sentences[:5]]
            
            logger.info(f"Extracted {len(scenes)} scenes from text parsing")
        
    except Exception as e:
        logger.error(f"Error extracting scenes: {str(e)}")
    
    # Return scenes (empty list if nothing found)
    return scenes
    return scenes

def generate_videos_for_scenes(scenes: List[Dict[str, Any]], original_prompt: str, role: str) -> List[Dict[str, Any]]:
    """
    Generate videos for each scene using external API.
    
    Args:
        scenes: List of scene descriptions with structured data
        original_prompt: Original user prompt for context
        role: AI role used for context
        
    Returns:
        List of video generation results
    """
    video_results = []
    
    for i, scene in enumerate(scenes):
        try:
            # Get scene description - handle both structured and simple formats
            if 'positive_prompt' in scene:
                # Use structured video script format
                scene_description = scene['positive_prompt']
                negative_prompt = scene.get('negative_prompt', '')
                duration = scene.get('duration', 10)
                visual_desc = scene.get('visual_description', '')
                voiceover = scene.get('voiceover', '')
                scene_number = scene.get('scene_number', i + 1)
                
                logger.info(f"Generating video for scene {scene_number}: {visual_desc[:100]}...")
            else:
                # Use simple format
                scene_description = scene.get('description', '')
                negative_prompt = ''
                duration = scene.get('duration', 10)
                visual_desc = scene_description
                voiceover = ''
                scene_number = i + 1
                
                logger.info(f"Generating video for scene {scene_number}: {scene_description[:100]}...")
              # Prepare the video generation request for Bytedance Seedance
            video_request = {
                'prompt': scene_description,
                'aspect_ratio': '9:21',  # YouTube Shorts aspect ratio
                'resolution': '480p',    # High quality
                'duration': 5 if duration <= 5 else 10,  # Seedance supports 5 or 10 seconds
                'camera_fixed': False,   # Allow camera movement for dynamic scenes
                'seed': -1              # Random seed
            }
            
            # Add master prompt context if available
            if 'master_prompt_context' in scene:
                master_context = scene['master_prompt_context']
                if master_context.get('positive_prefix'):
                    video_request['prompt'] = f"{master_context['positive_prefix']} {scene_description}"
            
            # Make request to external video generation API
            video_result = call_video_generation_api(video_request)
            
            video_results.append({
                'scene_index': i,
                'scene_number': scene_number,
                'scene_description': visual_desc,
                'voiceover': voiceover,
                'duration': duration,
                'video_request': video_request,
                'video_result': video_result,
                'status': 'success' if video_result.get('video_url') else 'failed'
            })
            
            # Add delay between requests to respect API rate limits
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Error generating video for scene {i+1}: {str(e)}")
            video_results.append({
                'scene_index': i,
                'scene_number': scene.get('scene_number', i + 1),
                'scene_description': scene.get('visual_description', scene.get('description', '')),
                'voiceover': scene.get('voiceover', ''),
                'duration': scene.get('duration', 10),
                'video_result': None,
                'status': 'failed',
                'error': str(e)
            })
    
    return video_results

def call_video_generation_api(video_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call Bytedance Seedance video generation API using FAL client.
    
    Args:
        video_request: Video generation parameters
        
    Returns:
        API response with video URL or error
    """
    try:
        if not FAL_KEY:
            logger.error("FAL_KEY environment variable not set")
            return {'error': 'FAL API key not configured'}
        
        # Set up FAL client with API key
        os.environ['FAL_KEY'] = FAL_KEY
        
        # def on_queue_update(update):
        #     if isinstance(update, fal_client.InProgress):
        #         for log in update.logs:
        #             logger.info(f"FAL Queue Update: {log.get('message', '')}")
        
        # logger.info(f"Submitting video generation request: {video_request}")
        
        # # Submit request to Bytedance Seedance via FAL
        # result = fal_client.subscribe(
        #     "fal-ai/bytedance/seedance/v1/lite/text-to-video",
        #     arguments=video_request,
        #     with_logs=True,
        #     on_queue_update=on_queue_update,
        # )
        time.sleep(2)
        result = {
            'video': {
                'url': ''
            }
        }
        
        logger.info(f"Video generation successful: {result}")
        
        # Extract video URL from result
        if result and 'video' in result and 'url' in result['video']:
            return {
                'video_url': result['video']['url'],
                'seed': result.get('seed'),
                'file_size': result['video'].get('file_size'),
                'content_type': result['video'].get('content_type', 'video/mp4'),
                'success': True
            }
        else:
            logger.error(f"No video URL in result: {result}")
            return {'error': 'No video URL in response', 'details': result}
            
    except Exception as e:
        logger.error(f"Error calling Bytedance Seedance API: {str(e)}")
        return {'error': 'API call failed', 'details': str(e)}

def store_video_results(video_results: List[Dict[str, Any]], prompt: str, role: str, ai_response: str) -> None:
    """
    Store video generation results in S3 or DynamoDB.
    
    Args:
        video_results: List of video generation results
        prompt: Original prompt
        role: AI role
        ai_response: AI response containing scenes
    """
    try:
        if not S3_BUCKET:
            raise ValueError("S3_BUCKET environment variable not set")
        
        # Create a summary of the video generation job
        job_summary = {
            'timestamp': int(time.time()),
            'original_prompt': prompt,
            'role': role,
            'ai_response': ai_response,
            'total_scenes': len(video_results),
            'successful_videos': len([r for r in video_results if r['status'] == 'success']),
            'failed_videos': len([r for r in video_results if r['status'] == 'failed']),
            'video_results': video_results
        }
        
        # Store in S3 as JSON
        s3_key = f"video-generations/{int(time.time())}-{hash(prompt) % 10000}.json"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(job_summary, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Stored video results in S3: {s3_key}")
            
    except Exception as e:
        logger.error(f"Error storing video results: {str(e)}")