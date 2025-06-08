output "api_gateway_rest_api_id" {
  description = "ID of the API Gateway REST API"
  value       = aws_api_gateway_rest_api.letmecook_api.id
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway REST API"
  value       = aws_api_gateway_rest_api.letmecook_api.execution_arn
}

output "api_gateway_invoke_url" {
  description = "Invoke URL of the API Gateway stage"
  value       = aws_api_gateway_stage.letmecook_stage.invoke_url
}

output "api_gateway_stage_name" {
  description = "Name of the API Gateway stage"
  value       = aws_api_gateway_stage.letmecook_stage.stage_name
}
