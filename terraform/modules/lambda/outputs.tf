output "request_script_invoke_arn" {
  description = "Invoke ARN of the request script Lambda function"
  value       = aws_lambda_function.request_script_from_deepseek.arn
}

output "request_media_generation_invoke_arn" {
  description = "Invoke ARN of the request video generation Lambda function"
  value       = aws_lambda_function.request_media_generation.arn
}

output "request_audio_generation_invoke_arn" {
  description = "Invoke ARN of the request audio generation Lambda function"
  value       = aws_lambda_function.request_audio_generation.arn
}
