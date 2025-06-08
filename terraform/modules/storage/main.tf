# Storage Module for LetMeCookAI
# Manages DynamoDB tables and SQS queues

# SQS Queue for job processing
resource "aws_sqs_queue" "job_queue" {
  name                      = "${var.app_name}-job-queue"
  delay_seconds            = 0
  max_message_size         = 262144
  message_retention_seconds = var.sqs_message_retention_seconds
  receive_wait_time_seconds = 10

  tags = var.tags
}

# DynamoDB table for job status tracking
resource "aws_dynamodb_table" "job_status" {
  name           = "${var.app_name}-job-status"
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

  tags = var.tags
}
