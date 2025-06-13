import json
import os
from typing import Any, Dict
import uuid
import boto3
from openai import OpenAI

# Explicitly type the SQS client
sqs = boto3.client('sqs', region_name='us-east-2')

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
    
    message_content = response.choices[0].message.content
    if not response or len(response.choices) == 0 or not message_content:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to get a valid response from the model"
            })
        }
    
    try:
        sqs.send_message(
            QueueUrl=os.environ['SQS_QUEUE_URL'],
            MessageBody=json.dumps({
                "prompt": prompt,
                "role": role,
                "response": message_content
            }),
            MessageGroupId=str(uuid.uuid4())  # Ensure unique group ID for FIFO queues
        )
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to send message to SQS",
                "details": str(e)
            })
        }
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Request processed successfully",
            "job_id": str(uuid.uuid4())
        })
    }