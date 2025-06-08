import json
import boto3
import logging
import os
from typing import Dict, Any

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
sts_client = boto3.client('sts')

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to validate IAM authentication and extract user identity.
    Note: With AWS_IAM authorization, API Gateway handles authentication automatically.
    This function processes requests that have already been authenticated.
    
    Args:
        event: API Gateway event with IAM authentication context
        context: Lambda context object
        
    Returns:
        User identity information for downstream processing
    """
    try:
        # Extract IAM user information from request context
        request_context = event.get('requestContext', {})
        identity = request_context.get('identity', {})
        
        # Get caller identity details
        caller_identity = get_caller_identity_from_context(request_context)
        
        if caller_identity:
            logger.info(f"Successfully authenticated IAM user: {caller_identity.get('user_id', 'unknown')}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'authenticated': True,
                    'user_identity': caller_identity
                })
            }
        else:
            logger.warning("Failed to extract user identity from IAM context")
            return {
                'statusCode': 401,
                'body': json.dumps({
                    'error': 'Authentication failed',
                    'message': 'Unable to verify user identity'
                })
            }
            
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'message': 'Authentication processing failed'
            })
        }

def get_caller_identity_from_context(request_context: Dict[str, Any]) -> Dict[str, Any] | None:
    """
    Extract user identity from API Gateway request context.
    
    Args:
        request_context: API Gateway request context
        
    Returns:
        User identity information if available, None otherwise
    """
    try:
        # API Gateway provides IAM user info in the identity section
        identity = request_context.get('identity', {})
        
        # Extract user ARN and ID
        user_arn = identity.get('userArn', '')
        access_key = identity.get('accessKey', '')
        account_id = identity.get('accountId', '')
        
        if user_arn and account_id:
            # Parse user ID from ARN
            # ARN format: arn:aws:iam::account:user/username
            user_id = user_arn.split('/')[-1] if '/' in user_arn else access_key
            
            return {
                'user_id': user_id,
                'user_arn': user_arn,
                'account_id': account_id,
                'access_key': access_key,
                'source_ip': identity.get('sourceIp', ''),
                'user_agent': identity.get('userAgent', '')
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error extracting identity from context: {str(e)}")
        return None

def validate_iam_permissions(user_arn: str, resource: str) -> bool:
    """
    Validate that the IAM user has permissions for the requested resource.
    
    Args:
        user_arn: IAM user ARN
        resource: Resource being accessed
        
    Returns:
        True if user has permissions, False otherwise
    """
    try:
        # In a real implementation, you might want to check specific permissions
        # For now, we trust that API Gateway has already validated IAM permissions
        logger.info(f"IAM permissions validated for user: {user_arn}")
        return True
        
    except Exception as e:
        logger.error(f"Error validating IAM permissions: {str(e)}")
        return False
