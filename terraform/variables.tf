# Variables for LetMeCookAI Terraform configuration

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "letmecook-ai"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "production"
}

variable "aws_region" {
  description = "AWS region for resource deployment"
  type        = string
  default     = "us-east-2"
}

variable "cognito_callback_urls" {
  description = "List of allowed callback URLs for Cognito"
  type        = list(string)
  default     = ["https://localhost:3000/callback"]
}

variable "cognito_logout_urls" {
  description = "List of allowed logout URLs for Cognito"
  type        = list(string)
  default     = ["https://localhost:3000/logout"]
}

variable "lambda_timeout" {
  description = "Timeout for Lambda functions in seconds"
  type        = number
  default     = 30
}

variable "lambda_runtime" {
  description = "Runtime for Lambda functions"
  type        = string
  default     = "python3.9"
}

variable "job_retention_days" {
  description = "Number of days to retain job records in DynamoDB"
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 14
}

variable "sqs_message_retention_seconds" {
  description = "Message retention period for SQS queue in seconds"
  type        = number
  default     = 1209600  # 14 days
}

variable "api_stage_name" {
  description = "API Gateway deployment stage name"
  type        = string
  default     = "prod"
}

variable "enable_api_logging" {
  description = "Enable API Gateway access logging"
  type        = bool
  default     = true
}

variable "cognito_password_minimum_length" {
  description = "Minimum password length for Cognito users"
  type        = number
  default     = 8
}

variable "max_prompt_length" {
  description = "Maximum allowed prompt length"
  type        = number
  default     = 2000
}

variable "min_prompt_length" {
  description = "Minimum required prompt length"
  type        = number
  default     = 10
}

variable "max_video_duration" {
  description = "Maximum allowed video duration in seconds"
  type        = number
  default     = 120
}

variable "min_video_duration" {
  description = "Minimum allowed video duration in seconds"
  type        = number
  default     = 5
}

variable "default_video_duration" {
  description = "Default video duration in seconds"
  type        = number
  default     = 30
}

variable "video_expiry_days" {
  description = "Number of days before generated videos expire"
  type        = number
  default     = 7
}

variable "max_retry_attempts" {
  description = "Maximum number of retry attempts for failed jobs"
  type        = number
  default     = 3
}

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
