# Output important resource information for API usage and monitoring

output "api_gateway_url" {
  description = "Base URL for the API Gateway"
  value       = "${aws_api_gateway_rest_api.letmecook_api.execution_arn}/${var.api_stage_name}"
}

output "api_gateway_invoke_url" {
  description = "Invoke URL for the API Gateway"
  value       = "https://${aws_api_gateway_rest_api.letmecook_api.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.api_stage_name}"
}

output "cognito_user_pool_id" {
  description = "Cognito User Pool ID for authentication"
  value       = aws_cognito_user_pool.letmecook_pool.id
}

output "cognito_user_pool_client_id" {
  description = "Cognito User Pool Client ID"
  value       = aws_cognito_user_pool_client.letmecook_client.id
}

output "cognito_user_pool_domain" {
  description = "Cognito User Pool domain for hosted UI"
  value       = aws_cognito_user_pool.letmecook_pool.domain
}

output "sqs_queue_url" {
  description = "SQS Queue URL for job processing"
  value       = aws_sqs_queue.job_queue.url
  sensitive   = true
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for job status tracking"
  value       = aws_dynamodb_table.job_status.name
}

output "lambda_function_names" {
  description = "Names of deployed Lambda functions"
  value = {
    auth_validator    = aws_lambda_function.auth_validator.function_name
    request_processor = aws_lambda_function.request_processor.function_name
    status_retriever  = aws_lambda_function.status_retriever.function_name
  }
}

output "api_endpoints" {
  description = "Available API endpoints"
  value = {
    submit_job     = "POST https://${aws_api_gateway_rest_api.letmecook_api.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.api_stage_name}/jobs"
    get_job_status = "GET https://${aws_api_gateway_rest_api.letmecook_api.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${var.api_stage_name}/jobs/{job_id}"
  }
}

output "cloudwatch_log_groups" {
  description = "CloudWatch Log Groups for monitoring"
  value = {
    auth_validator    = aws_cloudwatch_log_group.auth_validator_logs.name
    request_processor = aws_cloudwatch_log_group.request_processor_logs.name
    status_retriever  = aws_cloudwatch_log_group.status_retriever_logs.name
  }
}
