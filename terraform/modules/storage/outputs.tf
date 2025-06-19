output "sqs_queue_url" {
  description = "URL of the SQS job queue"
  value       = aws_sqs_queue.job_queue.url
}

output "sqs_queue_arn" {
  description = "ARN of the SQS job queue"
  value       = aws_sqs_queue.job_queue.arn
}

output "lambda_trigger_arn" {
  description = "ARN of the Lambda event source mapping for job queue"
  value       = aws_lambda_event_source_mapping.job_queue_trigger.arn
}

output "generated_video_bucket_name" {
  description = "Name of the S3 bucket for generated videos"
  value       = aws_s3_bucket.generated_videos_bucket.bucket
}

output "generated_video_bucket_arn" {
  description = "ARN of the S3 bucket for generated videos"
  value       = aws_s3_bucket.generated_videos_bucket.arn
}

output "job_coordination_table_name" {
  description = "Name of the DynamoDB job coordination table"
  value       = aws_dynamodb_table.job_coordination.name
}

output "job_coordination_table_arn" {
  description = "ARN of the DynamoDB job coordination table"
  value       = aws_dynamodb_table.job_coordination.arn
}
