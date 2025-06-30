import json
import os
import uuid
import boto3
from typing import Any, Dict
from openai import OpenAI

sqs = boto3.client('sqs', region_name='us-east-2')  # type: ignore

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Generate AI content and queue for video processing."""
    try:
        # Extract parameters from event
        params = extract_parameters(event)
        if 'error' in params:
            return error_response(400, params['error'])
        
        # Generate AI response
        ai_response = generate_ai_content(
            params['prompt'], 
            params['role'], 
            params['type']
        )
        
        # Queue for video generation
        queue_message(params, ai_response)
        
        return success_response(str(uuid.uuid4()))
        
    except Exception as e:
        return error_response(500, f"Processing failed: {str(e)}")

def extract_parameters(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and validate request parameters."""
    try:
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
            prompt = body.get('prompt')
            role = body.get('role')
            type_param = body.get('type')
        else:
            prompt = event.get('prompt')
            role = event.get('role')
            type_param = event.get('type')
        
        # Validate required fields
        if not prompt:
            return {'error': 'Prompt is required'}
        if not role:
            return {'error': 'Role is required'}
        if not type_param:
            return {'error': 'Type is required'}
        
        return {
            'prompt': prompt,
            'role': role,
            'type': type_param
        }
        
    except (json.JSONDecodeError, KeyError) as e:
        return {'error': f'Invalid request format: {str(e)}'}

def generate_ai_content(prompt: str, role: str, type_param: str) -> str:
    """Generate content using DeepSeek API."""
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-7185ba1cf1c640009d041e4cae8af71c")
    )
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": role},
            {"role": "user", "content": prompt}
        ],
        stream=False,
    )
    
    if not response.choices or not response.choices[0].message.content:
        raise ValueError("No valid response from AI model")
    
    return response.choices[0].message.content

def queue_message(params: Dict[str, Any], ai_response: str) -> None:
    """Queue message for video processing."""
    message_body = {
        "prompt": params['prompt'],
        "role": params['role'],
        "response": ai_response,
        "type": params['type'],
    }
    
    sqs.send_message(
        QueueUrl=os.environ['SQS_QUEUE_URL'],
        MessageBody=json.dumps(message_body)
    )

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