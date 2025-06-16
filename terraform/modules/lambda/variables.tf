variable "app_name" {
  description = "Name of the application"
  type        = string
}

variable "lambda_role_arn" {
  description = "ARN of the IAM role for Lambda functions"
  type        = string
}

variable "lambda_runtime" {
  description = "Runtime for Lambda functions"
  type        = string
  default     = "python3.9"
}

variable "lambda_timeout" {
  description = "Timeout for Lambda functions in seconds"
  type        = number
  default     = 60
}

variable "request_script_package_path" {
  description = "Path to the script-requester Lambda deployment package"
  type        = string
  default     = "lambda_packages/request_script.zip"
}

variable "request_video_generation_package_path" {
  description = "Path to the request video generation Lambda deployment package"
  type        = string
  default     = "lambda_packages/request_video_generation.zip"
}

variable "generated_videos_s3_bucket_name" {
  description = "Name of the S3 bucket for storing generated videos"
  type        = string
}

variable "sqs_queue_url" {
  description = "URL of the SQS queue for job processing"
  type        = string
}

variable "dynamodb_table_name" {
  description = "Name of the DynamoDB table for job status"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
