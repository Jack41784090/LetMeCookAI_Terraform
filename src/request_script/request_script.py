import json
import logging
import os
import uuid
import boto3
from typing import Any, Dict
from openai import OpenAI

# Configure logging with structured output
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create a custom formatter that includes extra fields
class StructuredFormatter(logging.Formatter):
    def format(self, record):
        # Get the base message
        base_msg = super().format(record)
        
        # Add extra fields if they exist
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName', 
                          'processName', 'process', 'getMessage', 'exc_info', 
                          'exc_text', 'stack_info', 'message']:
                extra_fields[key] = value
        
        if extra_fields:
            import json
            extra_json = json.dumps(extra_fields, default=str)
            return f"{base_msg} | EXTRA: {extra_json}"
        
        return base_msg

# Apply the formatter to existing handlers
for handler in logger.handlers:
    handler.setFormatter(StructuredFormatter())

# If no handlers exist, add one
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)

sqs = boto3.client('sqs', region_name='us-east-2')  # type: ignore

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Generate AI content and queue for video processing."""
    request_id = str(uuid.uuid4())
    logger.info(f"Processing request {request_id}", extra={
        "request_id": request_id,
        "event_keys": list(event.keys()) if event else []
    })
    
    try:
        # Extract parameters from event
        params = extract_parameters(event)
        if 'error' in params:
            logger.error(f"Parameter validation failed for request {request_id}: {params['error']}")
            return error_response(400, params['error'])
        
        logger.info(f"Parameters extracted successfully for request {request_id}", extra={
            "request_id": request_id,
            "type": params['type'],
            "prompt_length": len(params['prompt'])
        })
        
        # Generate AI response
        ai_response = generate_ai_content(
            params['prompt'], 
            params['role'], 
            params['type']
        )
        
        logger.info(f"AI content generated successfully for request {request_id}", extra={
            "request_id": request_id,
            "response_length": len(ai_response)
        })
        
        # Queue for video generation
        queue_message(params, ai_response)
        
        logger.info(f"Request {request_id} completed successfully and queued for video processing")
        return success_response(request_id)
        
    except Exception as e:
        logger.error(f"Request {request_id} failed with error: {str(e)}", extra={
            "request_id": request_id,
            "error_type": type(e).__name__
        }, exc_info=True)
        return error_response(500, f"Processing failed: {str(e)}")

def extract_parameters(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate request parameters."""
    logger.debug("Extracting parameters from event")
    
    try:
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
            prompt = body.get('prompt')
            role = body.get('role')
            type_param = body.get('type')
            logger.debug("Parameters extracted from event body")
        else:
            prompt = event.get('prompt')
            role = event.get('role')
            type_param = event.get('type')
            logger.debug("Parameters extracted directly from event")
        
        # Validate required fields
        if not prompt:
            logger.warning("Validation failed: Prompt is required")
            return {'error': 'Prompt is required'}
        if not role:
            logger.warning("Validation failed: Role is required")
            return {'error': 'Role is required'}
        if not type_param:
            logger.warning("Validation failed: Type is required")
            return {'error': 'Type is required'}
        
        logger.debug(f"Parameters validated successfully - type: {type_param}, prompt length: {len(prompt)}")
        return {
            'prompt': prompt,
            'role': role,
            'type': type_param
        }
        
    except (json.JSONDecodeError, KeyError) as e:
        error_msg = f'Invalid request format: {str(e)}'
        logger.error(f"Parameter extraction failed: {error_msg}")
        return {'error': error_msg}

def generate_ai_content(prompt: str, role: str, type_param: str) -> str:
    """Generate content using DeepSeek API."""
    logger.info(f"Generating AI content using DeepSeek API", extra={
        "model": "deepseek-chat",
        "type": type_param,
        "prompt_length": len(prompt)
    })
    
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-7185ba1cf1c640009d041e4cae8af71c")
    )
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": role},
                {"role": "user", "content": prompt}
            ],
            stream=False,
        )
        
        if not response.choices or not response.choices[0].message.content:
            logger.error("AI model returned empty response")
            raise ValueError("No valid response from AI model")
        
        content = response.choices[0].message.content
        
        # Extract usage information safely
        usage_tokens = None
        if hasattr(response, 'usage') and response.usage:
            usage_tokens = getattr(response.usage, 'total_tokens', None)
        
        logger.info(f"AI content generated successfully", extra={
            "response_length": len(content),
            "usage_tokens": usage_tokens
        })
        
        return content
        
    except Exception as e:
        logger.error(f"AI content generation failed: {str(e)}", extra={
            "error_type": type(e).__name__
        })
        raise

def queue_message(params: Dict[str, Any], ai_response: str) -> None:
    """Queue message for video processing."""
    logger.info("Queuing message for video processing", extra={
        "queue_url": os.environ.get('SQS_QUEUE_URL', 'NOT_SET'),
        "message_size": len(json.dumps({
            "prompt": params['prompt'],
            "role": params['role'],
            "response": ai_response,
            "type": params['type'],
        }))
    })
    
    message_body = {
        "prompt": params['prompt'],
        "role": params['role'],
        "response": ai_response,
        "type": params['type'],
    }
    
    try:
        response = sqs.send_message(
            QueueUrl=os.environ['SQS_QUEUE_URL'],
            MessageBody=json.dumps(message_body)
        )
        
        logger.info("Message successfully queued", extra={
            "message_id": response.get('MessageId'),
            "md5_of_body": response.get('MD5OfBody')
        })
        
    except Exception as e:
        logger.error(f"Failed to queue message: {str(e)}", extra={
            "error_type": type(e).__name__
        })
        raise

def error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Create error response."""
    return {
        "statusCode": status_code,
        "body": json.dumps({"error": message})
    }

def success_response(job_id: str) -> Dict[str, Any]:
    """Create success response."""
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Request processed successfully",
            "job_id": job_id
        })
    }