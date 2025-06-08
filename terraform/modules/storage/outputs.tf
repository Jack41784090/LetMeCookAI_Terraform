output "sqs_queue_url" {
  description = "URL of the SQS job queue"
  value       = aws_sqs_queue.job_queue.url
}

output "sqs_queue_arn" {
  description = "ARN of the SQS job queue"
  value       = aws_sqs_queue.job_queue.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB job status table"
  value       = aws_dynamodb_table.job_status.name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB job status table"
  value       = aws_dynamodb_table.job_status.arn
}
