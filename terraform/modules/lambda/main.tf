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

  timeout = 60 * 1

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
  timeout          = 60 * 15
  source_code_hash = filebase64sha256(var.request_media_generation_package_path)
  layers = [
    aws_lambda_layer_version.request_media_generation.arn
  ]

  environment {
    variables = {
      FAL_KEY                = var.fal_key
      JOB_QUEUE_URL          = var.sqs_queue_url
      S3_BUCKET              = var.generated_videos_s3_bucket_name
      COMPOSE_FUNCTION_NAME  = "${var.app_name}-compose-media"
      JOB_COORDINATION_TABLE = var.job_coordination_table_name
    }
  }

  tags = var.tags
}

resource "aws_lambda_layer_version" "compose_media_layer" {
  filename            = "lambda_packages/lambda-layer-compose_media.zip"
  layer_name          = "lambda-layer-compose_media"
  compatible_runtimes = ["python3.10"]
  source_code_hash    = filebase64sha256("lambda_packages/lambda-layer-compose_media.zip")
}

resource "aws_lambda_function" "compose_media" {
  filename      = var.compose_media_package_path
  function_name = "${var.app_name}-compose-media"
  role          = var.lambda_role_arn
  handler       = "compose_media.lambda_handler"
  runtime       = var.lambda_runtime
  timeout       = 60 * 15
  memory_size   = 3008
  source_code_hash = filebase64sha256(var.compose_media_package_path)
  layers = [
    aws_lambda_layer_version.compose_media_layer.arn,
    "arn:aws:lambda:us-east-2:252605744489:layer:ffmpeg:1"
  ]

  environment {
    variables = {
      S3_BUCKET              = var.generated_videos_s3_bucket_name
      JOB_COORDINATION_TABLE = var.job_coordination_table_name
    }
  }

  tags = var.tags
}
