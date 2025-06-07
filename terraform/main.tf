locals {
  app_name = var.app_name
  tags = merge({
    Environment = var.environment
    Project     = "LetMeCookAI"
    ManagedBy   = "Terraform"
  }, var.tags)
}

# Cognito User Pool for authentication
resource "aws_cognito_user_pool" "letmecook_pool" {
  name = "${local.app_name}-user-pool"
  password_policy {
    minimum_length    = var.cognito_password_minimum_length
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  auto_verified_attributes = ["email"]

  tags = local.tags
}

# Cognito User Pool Client
resource "aws_cognito_user_pool_client" "letmecook_client" {
  name         = "${local.app_name}-client"
  user_pool_id = aws_cognito_user_pool.letmecook_pool.id

  generate_secret                      = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["email", "openid", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls = var.cognito_callback_urls
  logout_urls   = var.cognito_logout_urls

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]
}

# SQS Queue for job processing
resource "aws_sqs_queue" "job_queue" {
  name                      = "${local.app_name}-job-queue"
  delay_seconds            = 0
  max_message_size         = 262144
  message_retention_seconds = 1209600  # 14 days
  receive_wait_time_seconds = 10

  tags = local.tags
}

# DynamoDB table for job status tracking
resource "aws_dynamodb_table" "job_status" {
  name           = "${local.app_name}-job-status"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  global_secondary_index {
    name            = "user-index"
    hash_key        = "user_id"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = local.tags
}

# IAM role for Lambda functions
resource "aws_iam_role" "lambda_role" {
  name = "${local.app_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = local.tags
}

# IAM policy for Lambda execution
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${local.app_name}-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.job_status.arn,
          "${aws_dynamodb_table.job_status.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.job_queue.arn
      },
      {
        Effect = "Allow"
        Action = [
          "cognito-idp:GetUser"
        ]
        Resource = aws_cognito_user_pool.letmecook_pool.arn
      }
    ]
  })
}

# Lambda function for authentication validation
resource "aws_lambda_function" "auth_validator" {
  filename         = "lambda_packages/auth_validator.zip"
  function_name    = "${local.app_name}-auth-validator"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout

  environment {
    variables = {
      USER_POOL_ID = aws_cognito_user_pool.letmecook_pool.id
      REGION       = data.aws_region.current.name
    }
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy.lambda_policy,
    aws_cloudwatch_log_group.auth_validator_logs
  ]
}

# Lambda function for request processing
resource "aws_lambda_function" "request_processor" {
  filename         = "lambda_packages/request_processor.zip"
  function_name    = "${local.app_name}-request-processor"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout

  environment {
    variables = {
      JOB_QUEUE_URL    = aws_sqs_queue.job_queue.url
      JOB_STATUS_TABLE = aws_dynamodb_table.job_status.name
      REGION           = data.aws_region.current.name
    }
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy.lambda_policy,
    aws_cloudwatch_log_group.request_processor_logs
  ]
}

# Lambda function for job status retrieval
resource "aws_lambda_function" "status_retriever" {
  filename         = "lambda_packages/status_retriever.zip"
  function_name    = "${local.app_name}-status-retriever"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = var.lambda_runtime
  timeout         = var.lambda_timeout

  environment {
    variables = {
      JOB_STATUS_TABLE = aws_dynamodb_table.job_status.name
      REGION           = data.aws_region.current.name
    }
  }

  tags = local.tags

  depends_on = [
    aws_iam_role_policy.lambda_policy,
    aws_cloudwatch_log_group.status_retriever_logs
  ]
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "auth_validator_logs" {
  name              = "/aws/lambda/${local.app_name}-auth-validator"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "request_processor_logs" {
  name              = "/aws/lambda/${local.app_name}-request-processor"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "status_retriever_logs" {
  name              = "/aws/lambda/${local.app_name}-status-retriever"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

# API Gateway REST API
resource "aws_api_gateway_rest_api" "letmecook_api" {
  name        = "${local.app_name}-api"
  description = "LetMeCookAI API for video generation requests"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = local.tags
}

# API Gateway Authorizer
resource "aws_api_gateway_authorizer" "cognito_authorizer" {
  name          = "${local.app_name}-cognito-authorizer"
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  type          = "COGNITO_USER_POOLS"
  provider_arns = [aws_cognito_user_pool.letmecook_pool.arn]
}

# API Gateway Resources
resource "aws_api_gateway_resource" "jobs" {
  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id
  parent_id   = aws_api_gateway_rest_api.letmecook_api.root_resource_id
  path_part   = "jobs"
}

resource "aws_api_gateway_resource" "job_status" {
  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id
  parent_id   = aws_api_gateway_resource.jobs.id
  path_part   = "{job_id}"
}

# POST /jobs - Submit new job
resource "aws_api_gateway_method" "submit_job" {
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  resource_id   = aws_api_gateway_resource.jobs.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id

  request_validator_id = aws_api_gateway_request_validator.request_validator.id
}

# GET /jobs/{job_id} - Get job status
resource "aws_api_gateway_method" "get_job_status" {
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  resource_id   = aws_api_gateway_resource.job_status.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Request Validator
resource "aws_api_gateway_request_validator" "request_validator" {
  name                        = "${local.app_name}-request-validator"
  rest_api_id                 = aws_api_gateway_rest_api.letmecook_api.id
  validate_request_body       = true
  validate_request_parameters = true
}

# API Gateway Integrations
resource "aws_api_gateway_integration" "submit_job_integration" {
  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id
  resource_id = aws_api_gateway_resource.jobs.id
  http_method = aws_api_gateway_method.submit_job.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.request_processor.invoke_arn
}

resource "aws_api_gateway_integration" "get_job_status_integration" {
  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id
  resource_id = aws_api_gateway_resource.job_status.id
  http_method = aws_api_gateway_method.get_job_status.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.status_retriever.invoke_arn
}

# Lambda permissions for API Gateway
resource "aws_lambda_permission" "api_gateway_request_processor" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.request_processor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.letmecook_api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "api_gateway_status_retriever" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.status_retriever.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.letmecook_api.execution_arn}/*/*"
}

# API Gateway Deployment
resource "aws_api_gateway_deployment" "letmecook_deployment" {
  depends_on = [
    aws_api_gateway_integration.submit_job_integration,
    aws_api_gateway_integration.get_job_status_integration
  ]

  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id

  lifecycle {
    create_before_destroy = true
  }
}

# API Gateway Stage
resource "aws_api_gateway_stage" "letmecook_stage" {
  deployment_id = aws_api_gateway_deployment.letmecook_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  stage_name    = var.api_stage_name

  tags = local.tags
}

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}