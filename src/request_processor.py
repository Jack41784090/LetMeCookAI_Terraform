import json
import boto3
import uuid
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client('sqs')
dynamodb = boto3.client('dynamodb')

JOB_QUEUE_URL = os.environ.get('JOB_QUEUE_URL')
JOB_STATUS_TABLE = os.environ.get('JOB_STATUS_TABLE')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process video generation requests and queue jobs."""
    try:
        # Extract user from IAM context
        user_arn = event.get('requestContext', {}).get('identity', {}).get('userArn', '')
        user_id = user_arn.split('/')[-1] if '/' in user_arn else ''
        
        if not user_id:
            return create_response(401, "User not authenticated")
        
        # Parse request body
        try:
            body = json.loads(event.get('body', '{}'))
        except json.JSONDecodeError:
            return create_response(400, "Invalid JSON format")
        
        # Validate request
        validation_error = validate_request(body)
        if validation_error:
            return create_response(400, validation_error)
        
        # Create and queue job
        job_id = str(uuid.uuid4())
        save_job_record(job_id, user_id, body)
        queue_job(job_id, body, user_id)
        
        logger.info(f"Created job {job_id} for user {user_id}")
        
        return create_response(201, {
            'job_id': job_id,
            'status': 'queued',
            'estimated_completion_time': (datetime.utcnow() + timedelta(minutes=10)).isoformat()
        })
        
    except Exception as e:
        logger.error(f"Request processing error: {str(e)}")
        return create_response(500, "Internal server error")

def validate_request(body: Dict[str, Any]) -> str | None:
    """Validate request parameters. Returns error message or None if valid."""
    if 'prompt' not in body:
        return 'Missing required field: prompt'
    
    prompt = body['prompt'].strip()
    if len(prompt) < 10:
        return 'Prompt must be at least 10 characters long'
    if len(prompt) > 2000:
        return 'Prompt must be less than 2000 characters'
    
    # Basic content filtering
    if re.search(r'\b(violence|gore|explicit|nsfw|adult)\b', prompt, re.IGNORECASE):
        return 'Prompt contains inappropriate content'
    
    # Validate optional parameters
    duration = body.get('duration', 30)
    if not isinstance(duration, (int, float)) or duration < 5 or duration > 120:
        return 'Duration must be between 5 and 120 seconds'
    
    quality = body.get('quality', 'standard')
    if quality not in ['standard', 'high', 'premium']:
        return 'Quality must be one of: standard, high, premium'
    
    return None

def save_job_record(job_id: str, user_id: str, body: Dict[str, Any]) -> None:
    """Save job record to DynamoDB."""
    if not JOB_STATUS_TABLE:
        raise ValueError("JOB_STATUS_TABLE not configured")
    
    now = datetime.utcnow()
    item = {
        'job_id': {'S': job_id},
        'user_id': {'S': user_id},
        'status': {'S': 'queued'},
        'prompt': {'S': body['prompt']},
        'duration': {'N': str(body.get('duration', 30))},
        'quality': {'S': body.get('quality', 'standard')},
        'created_at': {'S': now.isoformat()},
        'expires_at': {'N': str(int((now + timedelta(days=30)).timestamp()))}
    }
    
    dynamodb.put_item(TableName=JOB_STATUS_TABLE, Item=item)

def queue_job(job_id: str, body: Dict[str, Any], user_id: str) -> None:
    """Queue job for processing."""
    if not JOB_QUEUE_URL:
        raise ValueError("JOB_QUEUE_URL not configured")
    
    message = {
        'job_id': job_id,
        'user_id': user_id,
        'prompt': body['prompt'],
        'duration': body.get('duration', 30),
        'quality': body.get('quality', 'standard'),
        'created_at': datetime.utcnow().isoformat()
    }
    
    sqs.send_message(
        QueueUrl=JOB_QUEUE_URL,
        MessageBody=json.dumps(message),
        MessageAttributes={
            'JobId': {'StringValue': job_id, 'DataType': 'String'},
            'UserId': {'StringValue': user_id, 'DataType': 'String'}
        }
    )

def create_response(status_code: int, data: Any) -> Dict[str, Any]:
    """Create standardized API response."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'POST,GET,OPTIONS'
        },
        'body': json.dumps({
            'error': status_code >= 400,
            'data': data if status_code < 400 else None,
            'message': data if status_code >= 400 else 'Success',
            'timestamp': datetime.utcnow().isoformat()
        })
    }


