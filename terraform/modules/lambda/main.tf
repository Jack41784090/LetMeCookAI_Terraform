# Lambda Module for LetMeCookAI
# Manages Lambda functions and CloudWatch log groups

resource "aws_lambda_layer_version" "boto3_layer" {
  filename            = "lambda_packages/lambda-layer-boto3.zip"
  layer_name          = "lambda-layer-boto3"
  compatible_runtimes = ["python3.10"]
  source_code_hash    = filebase64sha256("lambda_packages/lambda-layer-boto3.zip")
}

resource "aws_lambda_layer_version" "request_script_from_deepseek_layer" {
  filename            = "lambda_packages/lambda-layer-request_script.zip"
  layer_name          = "lambda-layer-request_script"
  compatible_runtimes = ["python3.10"]
  source_code_hash    = filebase64sha256("lambda_packages/lambda-layer-request_script.zip")
}

resource "aws_lambda_function" "request_script_from_deepseek" {
  filename         = var.request_script_package_path
  function_name    = "${var.app_name}-request-script"
  role             = var.lambda_role_arn
  handler          = "request_script.lambda_handler"
  runtime          = "python3.10"
  source_code_hash = filebase64sha256(var.request_script_package_path)
  layers = [
    aws_lambda_layer_version.request_script_from_deepseek_layer.arn
  ]

  timeout = var.lambda_timeout

  environment {
    variables = {
      SQS_QUEUE_URL = var.sqs_queue_url
    }
  }
}

resource "aws_lambda_layer_version" "request_media_generation" {
  filename            = "lambda_packages/lambda-layer-request_media_generation.zip"
  layer_name          = "lambda-layer-request_media_generation"
  compatible_runtimes = ["python3.10"]
  source_code_hash    = filebase64sha256("lambda_packages/lambda-layer-request_media_generation.zip")
}

resource "aws_lambda_function" "request_media_generation" {
  filename         = var.request_media_generation_package_path
  function_name    = "${var.app_name}-request-video-generation"
  role             = var.lambda_role_arn
  handler          = "request_media_generation.lambda_handler"
  runtime          = var.lambda_runtime
  timeout          = var.lambda_timeout * 10 # Increased timeout for video generation
  source_code_hash = filebase64sha256(var.request_media_generation_package_path)
  layers = [
    aws_lambda_layer_version.request_media_generation.arn
  ]

  environment {
    variables = {
      FAL_KEY       = var.fal_key
      JOB_QUEUE_URL = var.sqs_queue_url
      S3_BUCKET     = var.generated_videos_s3_bucket_name
    }
  }

  tags = var.tags
}
