variable "request_script_lambda_arn" {
  description = "The arn of the lambda function that sends a request to DeepSeek to generate a YouTube script"
  type        = string
}

variable "request_script_lambda_role" {
  description = "The arn of the role assumed for the lambda execution"
  type        = string
}

