# Lambda Module for LetMeCookAI
# Manages Lambda functions and CloudWatch log groups

# Data sources
data "aws_region" "current" {}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "auth_validator_logs" {
  name              = "/aws/lambda/${var.app_name}-auth-validator"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "request_processor_logs" {
  name              = "/aws/lambda/${var.app_name}-request-processor"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "status_retriever_logs" {
  name              = "/aws/lambda/${var.app_name}-status-retriever"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Lambda function for authentication validation
resource "aws_lambda_function" "auth_validator" {
  filename         = var.auth_validator_package_path
  function_name    = "${var.app_name}-auth-validator"
  role            = var.lambda_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout
  
  environment {
    variables = {
      REGION = data.aws_region.current.name
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.auth_validator_logs]
}

# Lambda function for request processing
resource "aws_lambda_function" "request_processor" {
  filename         = var.request_processor_package_path
  function_name    = "${var.app_name}-request-processor"
  role            = var.lambda_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout

  environment {
    variables = {
      JOB_QUEUE_URL    = var.sqs_queue_url
      JOB_STATUS_TABLE = var.dynamodb_table_name
      REGION           = data.aws_region.current.name
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.request_processor_logs]
}

# Lambda function for job status retrieval
resource "aws_lambda_function" "status_retriever" {
  filename         = var.status_retriever_package_path
  function_name    = "${var.app_name}-status-retriever"
  role            = var.lambda_role_arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout

  environment {
    variables = {
      JOB_STATUS_TABLE = var.dynamodb_table_name
      REGION           = data.aws_region.current.name
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.status_retriever_logs]
}
