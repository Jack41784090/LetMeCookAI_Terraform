variable "app_name" {
  description = "Name of the application"
  type        = string
}

variable "sqs_message_retention_seconds" {
  description = "Message retention period for SQS queue in seconds"
  type        = number
  default     = 1209600  # 14 days
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "trigger_lambda_arn" {
  description = "ARN of the Lambda function to trigger when new messages arrive in job_queue"
  type        = string
}
