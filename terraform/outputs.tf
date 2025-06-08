# Output important resource information for API usage and monitoring

output "api_gateway_url" {
  description = "Base URL for the API Gateway"
  value       = "${module.api_gateway.api_gateway_execution_arn}/${var.api_stage_name}"
}

output "api_gateway_invoke_url" {
  description = "Invoke URL for the API Gateway"
  value       = module.api_gateway.api_gateway_invoke_url
}

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

output "api_endpoints" {
  description = "Available API endpoints"
  value = {
    submit_job     = "${module.api_gateway.api_gateway_invoke_url}/jobs"
    get_job_status = "${module.api_gateway.api_gateway_invoke_url}/jobs/{job_id}"
  }
}

output "iam_group_name" {
  description = "IAM group name for API users"
  value       = module.iam.api_users_group_name
}

output "region" {
  description = "AWS region where resources are deployed"
  value       = data.aws_region.current.name
}
