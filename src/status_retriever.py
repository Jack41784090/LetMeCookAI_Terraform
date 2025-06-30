import json
import boto3
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.client('dynamodb')
JOB_STATUS_TABLE = os.environ.get('JOB_STATUS_TABLE')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Retrieve job status and video URLs."""
    try:
        # Extract user from IAM context
        user_arn = event.get('requestContext', {}).get('identity', {}).get('userArn', '')
        user_id = user_arn.split('/')[-1] if '/' in user_arn else ''
        
        if not user_id:
            return create_response(401, "User not authenticated")
        
        # Get job_id from path parameters
        job_id = event.get('pathParameters', {}).get('job_id')
        if not job_id:
            return create_response(400, "Missing job_id parameter")
        
        # Get job status
        job_data = get_job_status(job_id, user_id)
        if not job_data:
            return create_response(404, "Job not found or access denied")
        
        return create_response(200, format_job_data(job_data))
        
    except Exception as e:
        logger.error(f"Error retrieving job status: {str(e)}")
        return create_response(500, "Internal server error")

def get_job_status(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get job status from DynamoDB with user access control."""
    if not JOB_STATUS_TABLE:
        raise ValueError("JOB_STATUS_TABLE not configured")
    
    try:
        response = dynamodb.get_item(
            TableName=JOB_STATUS_TABLE,
            Key={'job_id': {'S': job_id}}
        )
        
        if 'Item' not in response:
            return None
        
        item = response['Item']
        # Check user access
        if item.get('user_id', {}).get('S') != user_id:
            return None
        
        # Convert DynamoDB format to regular dict
        return {
            'job_id': item.get('job_id', {}).get('S', ''),
            'user_id': item.get('user_id', {}).get('S', ''),
            'status': item.get('status', {}).get('S', ''),
            'prompt': item.get('prompt', {}).get('S', ''),
            'duration': int(item.get('duration', {}).get('N', '30')),
            'quality': item.get('quality', {}).get('S', 'standard'),
            'created_at': item.get('created_at', {}).get('S', ''),
            'video_url': item.get('video_url', {}).get('S', ''),
            'error_message': item.get('error_message', {}).get('S', '')
        }
        
    except Exception as e:
        logger.error(f"Error getting job status: {str(e)}")
        raise

def format_job_data(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Format job data for API response."""
    return {
        'job_id': job_data['job_id'],
        'status': job_data['status'],
        'prompt': job_data['prompt'],
        'duration': job_data['duration'],
        'quality': job_data['quality'],
        'created_at': job_data['created_at'],
        'video_url': job_data.get('video_url'),
        'error_message': job_data.get('error_message')
    }

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


