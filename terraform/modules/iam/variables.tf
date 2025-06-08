variable "app_name" {
  description = "Name of the application"
  type        = string
}
variable "dynamodb_table_arn" {
  description = "DynamoDB table ARN for Lambda IAM policy"
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
