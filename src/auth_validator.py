import json
import logging
from typing import Dict, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Validate IAM authentication and extract user identity."""
    try:
        identity = event.get('requestContext', {}).get('identity', {})
        user_arn = identity.get('userArn', '')
        
        if not user_arn:
            return create_response(401, {'error': 'Authentication failed'})
        
        user_id = user_arn.split('/')[-1] if '/' in user_arn else identity.get('accessKey', '')
        
        return create_response(200, {
            'authenticated': True,
            'user_identity': {
                'user_id': user_id,
                'user_arn': user_arn,
                'account_id': identity.get('accountId', ''),
                'access_key': identity.get('accessKey', ''),
                'source_ip': identity.get('sourceIp', ''),
                'user_agent': identity.get('userAgent', '')
            }
        })
        
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return create_response(500, {'error': 'Authentication processing failed'})

def create_response(status_code: int, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create standardized response."""
    return {
        'statusCode': status_code,
        'body': json.dumps(data)
    }

