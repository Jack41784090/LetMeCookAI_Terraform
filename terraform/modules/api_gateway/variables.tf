variable "app_name" {
  description = "Name of the application"
  type        = string
}

variable "api_stage_name" {
  description = "API Gateway deployment stage name"
  type        = string
  default     = "prod"
}

variable "request_processor_invoke_arn" {
  description = "Invoke ARN of the request processor Lambda function"
  type        = string
}

variable "status_retriever_invoke_arn" {
  description = "Invoke ARN of the status retriever Lambda function"
  type        = string
}

variable "request_processor_function_name" {
  description = "Name of the request processor Lambda function"
  type        = string
}

variable "status_retriever_function_name" {
  description = "Name of the status retriever Lambda function"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
