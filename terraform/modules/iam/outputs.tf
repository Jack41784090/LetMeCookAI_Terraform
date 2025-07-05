output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_role.arn
}

output "scheduler_role_arn" {
  description = "ARN of the EventBridge Scheduler execution role"
  value       = aws_iam_role.scheduler_role.arn
}
