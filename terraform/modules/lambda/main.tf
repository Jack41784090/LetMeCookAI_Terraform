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
  filename      = var.auth_validator_package_path
  function_name = "${var.app_name}-auth-validator"
  role          = var.lambda_role_arn
  handler       = "auth_validator.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  source_code_hash = filebase64sha256(var.auth_validator_package_path)

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
  filename      = var.request_processor_package_path
  function_name = "${var.app_name}-request-processor"
  role          = var.lambda_role_arn
  handler       = "request_processor.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  source_code_hash = filebase64sha256(var.request_processor_package_path)

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
  filename      = var.status_retriever_package_path
  function_name = "${var.app_name}-status-retriever"
  role          = var.lambda_role_arn
  handler       = "status_retriever.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = var.lambda_timeout
  source_code_hash = filebase64sha256(var.status_retriever_package_path)

  environment {
    variables = {
      JOB_STATUS_TABLE = var.dynamodb_table_name
      REGION           = data.aws_region.current.name
    }
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.status_retriever_logs]
}

resource "aws_lambda_layer_version" "request_script_from_deepseek_layer" {
  filename = "lambda_packages/lambda-layer-request_script.zip"
  layer_name = "lambda-layer-request_script"
  compatible_runtimes = ["python3.10"]
  source_code_hash = filebase64sha256("lambda_packages/lambda-layer-request_script.zip")
}

resource "aws_lambda_function" "request_script_from_deepseek" {
  filename = var.request_script_package_path
  function_name = "${var.app_name}-request-script"
  role          = var.lambda_role_arn
  handler       = "request_script.lambda_handler"
  runtime = "python3.10"
  source_code_hash = filebase64sha256(var.request_script_package_path)
  layers = [
    aws_lambda_layer_version.request_script_from_deepseek_layer.arn
  ]

  environment {
    variables = {
      SQS_QUEUE_URL = var.sqs_queue_url
    }
  }
}
