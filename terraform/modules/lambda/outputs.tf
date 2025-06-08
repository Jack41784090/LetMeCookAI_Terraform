output "auth_validator_function_name" {
  description = "Name of the auth validator Lambda function"
  value       = aws_lambda_function.auth_validator.function_name
}

output "auth_validator_invoke_arn" {
  description = "Invoke ARN of the auth validator Lambda function"
  value       = aws_lambda_function.auth_validator.invoke_arn
}

output "request_processor_function_name" {
  description = "Name of the request processor Lambda function"
  value       = aws_lambda_function.request_processor.function_name
}

output "request_processor_invoke_arn" {
  description = "Invoke ARN of the request processor Lambda function"
  value       = aws_lambda_function.request_processor.invoke_arn
}

output "status_retriever_function_name" {
  description = "Name of the status retriever Lambda function"
  value       = aws_lambda_function.status_retriever.function_name
}

output "status_retriever_invoke_arn" {
  description = "Invoke ARN of the status retriever Lambda function"
  value       = aws_lambda_function.status_retriever.invoke_arn
}
