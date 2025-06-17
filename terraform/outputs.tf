# Output important resource information for API usage and monitoring

output "sqs_queue_url" {
  description = "SQS Queue URL for job processing"
  value       = module.storage.sqs_queue_url
  sensitive   = true
}

output "region" {
  description = "AWS region where resources are deployed"
  value       = data.aws_region.current.name
}
