# Output important resource information for API usage and monitoring

output "sqs_queue_url" {
  description = "SQS Queue URL for job processing"
  value       = module.storage.sqs_queue_url
  sensitive   = true
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for job status tracking"
  value       = module.storage.dynamodb_table_name
}

output "lambda_function_names" {
  description = "Names of deployed Lambda functions"
  value = {
    auth_validator    = module.lambda.auth_validator_function_name
    request_processor = module.lambda.request_processor_function_name
    status_retriever  = module.lambda.status_retriever_function_name
  }
}

output "region" {
  description = "AWS region where resources are deployed"
  value       = data.aws_region.current.name
}
