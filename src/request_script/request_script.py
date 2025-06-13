import json
from typing import Any, Dict
import uuid
from openai import OpenAI

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        if 'body' in event:
            body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
            prompt = body.get('prompt')
            role = body.get('role')
        else:
            prompt = event.get('prompt')
            role = event.get('role')
    except (json.JSONDecodeError, KeyError) as e:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Invalid JSON input or missing prompt field",
                "details": str(e)
            })
        }
        
    if not prompt:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Prompt is required"
            })
        }
    if not role:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Role is required"
            })
        }
    
    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key="sk-7185ba1cf1c640009d041e4cae8af71c"
    )

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            { "role": "system", "content": role },
            { "role": "user", "content": prompt }
        ],
        stream=False,
    )
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Request processed successfully",
            "job_id": str(uuid.uuid4())
        })
    }