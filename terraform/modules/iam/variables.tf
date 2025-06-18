variable "app_name" {
  description = "Name of the application"
  type        = string
}

variable "sqs_queue_arn" {
  description = "SQS queue ARN for Lambda IAM policy"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "generated_video_bucket_arn" {
  description = "The bucket arn in which holds the generated videos"
  type = string
}
