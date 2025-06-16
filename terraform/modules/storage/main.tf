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

# Lambda event source mapping for SQS queue trigger
resource "aws_lambda_event_source_mapping" "job_queue_trigger" {
  event_source_arn = aws_sqs_queue.job_queue.arn
  function_name    = var.trigger_lambda_arn
  batch_size       = 10
  
  depends_on = [aws_sqs_queue.job_queue]
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

resource "aws_s3_bucket" "generated_videos_bucket" {
  bucket = "${var.app_name}-generated-videos"

  tags = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_acl" "generated_videos_bucket_acl" {
  bucket = aws_s3_bucket.generated_videos_bucket.id
  acl    = "private"
}
