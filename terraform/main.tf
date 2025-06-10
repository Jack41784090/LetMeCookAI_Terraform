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
}

# IAM Module - Roles, policies, and groups
module "iam" {
  source             = "./modules/iam"
  app_name           = local.app_name
  dynamodb_table_arn = module.storage.dynamodb_table_arn
  sqs_queue_arn      = module.storage.sqs_queue_arn
  tags               = local.tags
}

# Lambda Module - Lambda functions and CloudWatch logs
module "lambda" {
  source                         = "./modules/lambda"
  app_name                       = local.app_name
  lambda_role_arn                = module.iam.lambda_role_arn
  lambda_runtime                 = var.lambda_runtime
  lambda_timeout                 = var.lambda_timeout
  log_retention_days             = var.log_retention_days
  request_script_package_path    = "lambda_packages/request_script.zip"
  auth_validator_package_path    = "lambda_packages/auth_validator.zip"
  request_processor_package_path = "lambda_packages/request_processor.zip"
  status_retriever_package_path  = "lambda_packages/status_retriever.zip"
  sqs_queue_url                  = module.storage.sqs_queue_url
  dynamodb_table_name            = module.storage.dynamodb_table_name
  tags                           = local.tags
}

module "scheduler" {
  source                     = "./modules/scheduler"
  request_script_lambda_arn  = module.lambda.request_script_invoke_arn
  request_script_lambda_role = module.iam.lambda_role_arn
}

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
