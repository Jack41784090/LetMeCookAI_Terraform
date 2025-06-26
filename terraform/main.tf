locals {
  app_name = var.app_name
  tags = merge({
    Environment = var.environment
    Project     = "LetMeCookAI"
    ManagedBy   = "Terraform"
  }, var.tags)
}

# Storage Module - DynamoDB and SQS
module "storage" {
  source                        = "./modules/storage"
  app_name                      = local.app_name
  sqs_message_retention_seconds = var.sqs_message_retention_seconds
  tags                          = local.tags
  media_generation_invoke_arn   = module.lambda.request_media_generation_invoke_arn
}

# IAM Module - Roles, policies, and groups
module "iam" {
  source                     = "./modules/iam"
  app_name                   = local.app_name
  sqs_queue_arn              = module.storage.sqs_queue_arn
  tags                       = local.tags
  generated_video_bucket_arn = module.storage.generated_video_bucket_arn
  job_coordination_table_arn = module.storage.job_coordination_table_arn
  compose_media_function_arn = module.lambda.compose_media_invoke_arn
}

# Lambda Module - Lambda functions and CloudWatch logs
module "lambda" {
  source                          = "./modules/lambda"
  app_name                        = local.app_name
  lambda_role_arn                 = module.iam.lambda_role_arn
  lambda_runtime                  = "python3.10"
  lambda_timeout                  = var.lambda_timeout
  request_script_package_path     = "lambda_packages/request_script.zip"
  sqs_queue_url                   = module.storage.sqs_queue_url
  generated_videos_s3_bucket_name = module.storage.generated_video_bucket_name
  fal_key                         = var.fal_key
  compose_media_package_path      = "lambda_packages/compose_media.zip"
  job_coordination_table_name     = module.storage.job_coordination_table_name
  youtube_client_id               = var.youtube_client_id
  youtube_client_secret           = var.youtube_client_secret
  youtube_refresh_token           = var.youtube_refresh_token
  
}

module "scheduler" {
  source                     = "./modules/scheduler"
  request_script_lambda_arn  = module.lambda.request_script_invoke_arn
  request_script_lambda_role = module.iam.lambda_role_arn
}

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
