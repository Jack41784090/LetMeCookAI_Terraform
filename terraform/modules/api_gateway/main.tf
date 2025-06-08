# API Gateway Module for LetMeCookAI
# Manages API Gateway resources, methods, and integrations

# API Gateway REST API
resource "aws_api_gateway_rest_api" "letmecook_api" {
  name        = "${var.app_name}-api"
  description = "LetMeCookAI API for video generation requests"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = var.tags
}

# API Gateway IAM Authorizer
resource "aws_api_gateway_authorizer" "iam_authorizer" {
  name          = "${var.app_name}-iam-authorizer"
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  type          = "AWS_IAM"
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
  authorization = "AWS_IAM"

  request_validator_id = aws_api_gateway_request_validator.request_validator.id
}

# GET /jobs/{job_id} - Get job status
resource "aws_api_gateway_method" "get_job_status" {
  rest_api_id   = aws_api_gateway_rest_api.letmecook_api.id
  resource_id   = aws_api_gateway_resource.job_status.id
  http_method   = "GET"
  authorization = "AWS_IAM"
}

# Request Validator
resource "aws_api_gateway_request_validator" "request_validator" {
  name                        = "${var.app_name}-request-validator"
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
  uri                     = var.request_processor_invoke_arn
}

resource "aws_api_gateway_integration" "get_job_status_integration" {
  rest_api_id = aws_api_gateway_rest_api.letmecook_api.id
  resource_id = aws_api_gateway_resource.job_status.id
  http_method = aws_api_gateway_method.get_job_status.http_method

  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = var.status_retriever_invoke_arn
}

# Lambda permissions for API Gateway
resource "aws_lambda_permission" "api_gateway_request_processor" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = var.request_processor_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.letmecook_api.execution_arn}/*/*"
}

resource "aws_lambda_permission" "api_gateway_status_retriever" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = var.status_retriever_function_name
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

  tags = var.tags
}
