output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_role.arn
}

output "api_users_group_name" {
  description = "Name of the API users IAM group"
  value       = aws_iam_group.api_users.name
}

output "api_user_policy_arn" {
  description = "ARN of the API user policy"
  value       = aws_iam_policy.api_user_policy.arn
}
