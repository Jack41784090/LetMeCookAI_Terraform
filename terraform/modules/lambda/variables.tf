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

variable "request_media_generation_package_path" {
  description = "Path to the request video generation Lambda deployment package"
  type        = string
  default     = "lambda_packages/request_media_generation.zip"
}

variable "generated_videos_s3_bucket_name" {
  description = "Name of the S3 bucket for storing generated videos"
  type        = string
}

variable "fal_key" {
  description = "API key for FAL service"
  type        = string
}

variable "sqs_queue_url" {
  description = "URL of the SQS queue for job processing"
  type        = string
}

variable "compose_media_package_path" {
  description = "Path to the compose media Lambda deployment package"
  type        = string
  default     = "lambda_packages/compose_media.zip"
}

variable "job_coordination_table_name" {
  description = "Name of the DynamoDB table for job coordination"
  type        = string
}

variable "upload_youtube_package_path" {
  description = "Path to the upload YouTube Lambda deployment package"
  type        = string
  default     = "lambda_packages/upload_youtube.zip"
}

variable "youtube_client_id" {
  description = "YouTube API OAuth client ID"
  type        = string
  sensitive   = true
}

variable "youtube_client_secret" {
  description = "YouTube API OAuth client secret"
  type        = string
  sensitive   = true
}

variable "youtube_refresh_token" {
  description = "YouTube API OAuth refresh token"
  type        = string
  sensitive   = true
}
