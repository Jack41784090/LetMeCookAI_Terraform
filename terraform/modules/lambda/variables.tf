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
  default     = 30
}

variable "log_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 14
}

variable "request_script_package_path" {
  description = "Path to the script-requester Lambda deployment package"
  type        = string
  default     = "lambda_packages/request_script.zip"
}

variable "auth_validator_package_path" {
  description = "Path to the auth validator Lambda deployment package"
  type        = string
  default     = "lambda_packages/auth_validator.zip"
}

variable "request_processor_package_path" {
  description = "Path to the request processor Lambda deployment package"
  type        = string
  default     = "lambda_packages/request_processor.zip"
}

variable "status_retriever_package_path" {
  description = "Path to the status retriever Lambda deployment package"
  type        = string
  default     = "lambda_packages/status_retriever.zip"
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
