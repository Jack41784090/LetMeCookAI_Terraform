import json
import boto3
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.client('dynamodb')

# Environment variables
JOB_STATUS_TABLE = os.environ.get('JOB_STATUS_TABLE')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to retrieve job status and video URLs.
    
    Args:
        event: API Gateway event containing job_id parameter
        context: Lambda context object
        
    Returns:
        API Gateway response with job status or error message
    """
    try:
        # Extract user information from authorizer context
        user_context = event.get('requestContext', {}).get('authorizer', {})
        user_id = user_context.get('user_id')
        
        if not user_id:
            logger.error("User ID not found in request context")
            return create_error_response(401, "Unauthorized - User not authenticated")
        
        # Extract job_id from path parameters
        path_params = event.get('pathParameters') or {}
        job_id = path_params.get('job_id')
        
        if not job_id:
            return create_error_response(400, "Missing required parameter: job_id")
        
        # Retrieve job status from DynamoDB
        job_data = get_job_status(job_id, user_id)
        
        if not job_data:
            return create_error_response(404, "Job not found or access denied")
        
        # Format response based on job status
        response_data = format_job_response(job_data)
        
        logger.info(f"Retrieved job status for job_id: {job_id}, status: {job_data.get('status')}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,Authorization',
                'Access-Control-Allow-Methods': 'POST,GET,OPTIONS'
            },
            'body': json.dumps(response_data)
        }
        
    except Exception as e:
        logger.error(f"Error retrieving job status: {str(e)}")
        return create_error_response(500, "Internal server error")

def get_job_status(job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve job status from DynamoDB, ensuring user owns the job.
    
    Args:
        job_id: Job identifier
        user_id: User identifier for access control
        
    Returns:
        Job data if found and user has access, None otherwise
    """
    try:
        table = dynamodb.Table(JOB_STATUS_TABLE)
        
        response = table.get_item(
            Key={'job_id': job_id}
        )
        
        job_item = response.get('Item')
        
        # Check if job exists and user has access
        if not job_item or job_item.get('user_id') != user_id:
            logger.warning(f"Job {job_id} not found or access denied for user {user_id}")
            return None
        
        return job_item
        
    except Exception as e:
        logger.error(f"Error retrieving job from DynamoDB: {str(e)}")
        raise

def format_job_response(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format job data for API response.
    
    Args:
        job_data: Raw job data from DynamoDB
        
    Returns:
        Formatted response data
    """
    status = job_data.get('status', 'unknown')
    
    # Base response
    response = {
        'job_id': job_data.get('job_id'),
        'status': status,
        'created_at': job_data.get('created_at'),
        'updated_at': job_data.get('updated_at'),
        'prompt': job_data.get('prompt'),
        'duration': job_data.get('duration'),
        'quality': job_data.get('quality')
    }
    
    # Add status-specific information
    if status == 'queued':
        response.update({
            'message': 'Job is queued for processing',
            'estimated_completion_time': job_data.get('estimated_completion'),
            'position_in_queue': estimate_queue_position(job_data)
        })
    
    elif status == 'processing':
        response.update({
            'message': 'Job is currently being processed',
            'progress_percentage': job_data.get('progress_percentage', 0),
            'estimated_completion_time': job_data.get('estimated_completion')
        })
    
    elif status == 'completed':
        response.update({
            'message': 'Job completed successfully',
            'video_url': job_data.get('video_url'),
            'video_duration': job_data.get('actual_duration'),
            'file_size': job_data.get('file_size'),
            'expires_at': job_data.get('video_expires_at')
        })
    
    elif status == 'failed':
        response.update({
            'message': 'Job processing failed',
            'error_message': job_data.get('error_message', 'Unknown error occurred'),
            'retry_count': job_data.get('retry_count', 0),
            'can_retry': job_data.get('retry_count', 0) < 3
        })
    
    elif status == 'cancelled':
        response.update({
            'message': 'Job was cancelled',
            'cancellation_reason': job_data.get('cancellation_reason', 'User requested')
        })
    
    else:
        response.update({
            'message': f'Job status: {status}'
        })
    
    return response

def estimate_queue_position(job_data: Dict[str, Any]) -> int:
    """
    Estimate position in queue based on creation time.
    
    Args:
        job_data: Job data containing creation timestamp
        
    Returns:
        Estimated position in queue
    """
    try:
        table = dynamodb.Table(JOB_STATUS_TABLE)
        
        # Query jobs with same or higher priority created before this job
        job_created_at = job_data.get('created_at')
        
        # Simple estimation: count queued jobs created before this one
        response = table.scan(
            FilterExpression='#status = :status AND created_at < :created_at',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':status': 'queued',
                ':created_at': job_created_at
            },
            Select='COUNT'
        )
        
        return response.get('Count', 0) + 1
        
    except Exception as e:
        logger.warning(f"Error estimating queue position: {str(e)}")
        return 1  # Default to position 1 if estimation fails

def calculate_video_expiry(updated_at: str) -> str:
    """
    Calculate video URL expiry time.
    
    Args:
        updated_at: Job completion timestamp
        
    Returns:
        Expiry timestamp string
    """
    try:
        from datetime import datetime, timedelta
        
        completion_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        expiry_time = completion_time + timedelta(days=7)  # Videos expire after 7 days
        
        return expiry_time.isoformat()
        
    except Exception as e:
        logger.warning(f"Error calculating video expiry: {str(e)}")
        return "Unknown"

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
