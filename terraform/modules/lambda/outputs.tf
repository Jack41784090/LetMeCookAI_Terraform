output "request_script_invoke_arn" {
  description = "Invoke ARN of the request script Lambda function"
  value       = aws_lambda_function.request_script_from_deepseek.arn
}

output "request_media_generation_invoke_arn" {
  description = "Invoke ARN of the request video generation Lambda function"
  value       = aws_lambda_function.request_media_generation.arn
}

output "compose_media_invoke_arn" {
  description = "Invoke ARN of the compose media Lambda function"
  value       = aws_lambda_function.compose_media.invoke_arn
}

output "upload_youtube_invoke_arn" {
  description = "Invoke ARN of the upload YouTube Lambda function"
  value       = aws_lambda_function.upload_youtube.invoke_arn
}

output "upload_youtube_function_name" {
  description = "Name of the upload YouTube Lambda function"
  value       = aws_lambda_function.upload_youtube.function_name
}
