import json
import boto3
import uuid
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any
import re

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sqs = boto3.client('sqs')
dynamodb = boto3.client('dynamodb')

# Environment variables
JOB_QUEUE_URL = os.environ.get('JOB_QUEUE_URL')
JOB_STATUS_TABLE = os.environ.get('JOB_STATUS_TABLE')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to process video generation requests and queue jobs.
    
    Args:
        event: API Gateway event containing request data
        context: Lambda context object
        
    Returns:
        API Gateway response with job ID or error message
    """
    try:
        # Extract user information from IAM request context
        request_context = event.get('requestContext', {})
        identity = request_context.get('identity', {})
        
        # Get user ID from IAM identity
        user_arn = identity.get('userArn', '')
        user_id = user_arn.split('/')[-1] if '/' in user_arn else identity.get('accessKey', '')
        
        if not user_id:
            logger.error("User ID not found in IAM request context")
            return create_error_response(401, "Unauthorized - User not authenticated")
        
        # Parse and validate request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            logger.error("Invalid JSON in request body")
            return create_error_response(400, "Invalid JSON format")
        
        # Validate prompt
        validation_result = validate_prompt(body)
        if not validation_result['valid']:
            return create_error_response(400, validation_result['message'])
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # Create job record in DynamoDB
        job_record = create_job_record(job_id, user_id, body)
        save_job_status(job_record)
        
        # Queue job for processing
        queue_job(job_id, body, user_id)
        
        logger.info(f"Successfully created job {job_id} for user {user_id}")
        
        return {
            'statusCode': 201,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,Authorization',
                'Access-Control-Allow-Methods': 'POST,GET,OPTIONS'
            },
            'body': json.dumps({
                'job_id': job_id,
                'status': 'queued',
                'message': 'Job successfully queued for processing',
                'estimated_completion_time': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return create_error_response(500, "Internal server error")

def validate_prompt(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate the incoming prompt request.
    
    Args:
        body: Request body containing prompt and parameters
        
    Returns:
        Validation result with 'valid' boolean and 'message' string
    """
    # Check required fields
    if 'prompt' not in body:
        return {'valid': False, 'message': 'Missing required field: prompt'}
    
    prompt = body['prompt'].strip()
    
    # Validate prompt length
    if len(prompt) < 10:
        return {'valid': False, 'message': 'Prompt must be at least 10 characters long'}
    
    if len(prompt) > 2000:
        return {'valid': False, 'message': 'Prompt must be less than 2000 characters'}
    
    # Check for inappropriate content (basic filtering)
    inappropriate_patterns = [
        r'\b(violence|gore|explicit)\b',
        r'\b(nsfw|adult)\b'
    ]
    
    for pattern in inappropriate_patterns:
        if re.search(pattern, prompt, re.IGNORECASE):
            return {'valid': False, 'message': 'Prompt contains inappropriate content'}
    
    # Validate optional parameters
    duration = body.get('duration', 30)
    if not isinstance(duration, (int, float)) or duration < 5 or duration > 120:
        return {'valid': False, 'message': 'Duration must be between 5 and 120 seconds'}
    
    quality = body.get('quality', 'standard')
    if quality not in ['standard', 'high', 'premium']:
        return {'valid': False, 'message': 'Quality must be one of: standard, high, premium'}
    
    return {'valid': True, 'message': 'Valid prompt'}

def create_job_record(job_id: str, user_id: str, request_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a job record for DynamoDB storage.
    
    Args:
        job_id: Unique job identifier
        user_id: User identifier
        request_body: Original request parameters
        
    Returns:
        Job record dictionary
    """
    now = datetime.utcnow()
    
    return {
        'job_id': job_id,
        'user_id': user_id,
        'status': 'queued',
        'prompt': request_body['prompt'],
        'duration': request_body.get('duration', 30),
        'quality': request_body.get('quality', 'standard'),
        'created_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'expires_at': int((now + timedelta(days=30)).timestamp()),  # TTL for cleanup
        'retry_count': 0,
        'error_message': None,
        'video_url': None,
        'estimated_completion': (now + timedelta(minutes=10)).isoformat()
    }

def save_job_status(job_record: Dict[str, Any]) -> None:
    """
    Save job record to DynamoDB.
    
    Args:
        job_record: Job data to save
    """
    try:
        table = dynamodb.Table(JOB_STATUS_TABLE)
        table.put_item(Item=job_record)
        logger.info(f"Saved job record for job_id: {job_record['job_id']}")
    except Exception as e:
        logger.error(f"Error saving job record: {str(e)}")
        raise

def queue_job(job_id: str, request_body: Dict[str, Any], user_id: str) -> None:
    """
    Queue job for processing in SQS.
    
    Args:
        job_id: Unique job identifier
        request_body: Request parameters
        user_id: User identifier
    """
    try:
        message_body = {
            'job_id': job_id,
            'user_id': user_id,
            'prompt': request_body['prompt'],
            'duration': request_body.get('duration', 30),
            'quality': request_body.get('quality', 'standard'),
            'created_at': datetime.utcnow().isoformat()
        }
        
        sqs.send_message(
            QueueUrl=JOB_QUEUE_URL,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                'JobId': {
                    'StringValue': job_id,
                    'DataType': 'String'
                },
                'UserId': {
                    'StringValue': user_id,
                    'DataType': 'String'
                },
                'Priority': {
                    'StringValue': request_body.get('quality', 'standard'),
                    'DataType': 'String'
                }
            }
        )
        
        logger.info(f"Queued job {job_id} for processing")
        
    except Exception as e:
        logger.error(f"Error queuing job: {str(e)}")
        raise

def create_error_response(status_code: int, message: str) -> Dict[str, Any]:
    """
    Create standardized error response.
    
    Args:
        status_code: HTTP status code
        message: Error message
        
    Returns:
        API Gateway error response
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,GET,OPTIONS'
        },
        'body': json.dumps({
            'error': True,
            'message': message,
            'timestamp': datetime.utcnow().isoformat()
        })
    }
