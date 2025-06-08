# IAM Module for LetMeCookAI
# Manages IAM groups, policies, and roles

# IAM User Group for API access
resource "aws_iam_group" "api_users" {
  name = "${var.app_name}-api-users"
  path = "/"
}

# IAM Policy for API users
resource "aws_iam_policy" "api_user_policy" {
  name        = "${var.app_name}-api-user-policy"
  description = "Policy for LetMeCookAI API users"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "execute-api:Invoke"
        ]
        Resource = "${var.api_gateway_execution_arn}/*"
        Condition = {
          StringEquals = {
            "aws:userid" = "$${aws:userid}"
          }
        }
      }
    ]
  })

  tags = var.tags
}

# Attach policy to group
resource "aws_iam_group_policy_attachment" "api_users_policy" {
  group      = aws_iam_group.api_users.name
  policy_arn = aws_iam_policy.api_user_policy.arn
}

# IAM role for Lambda functions
resource "aws_iam_role" "lambda_role" {
  name = "${var.app_name}-lambda-role"

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

  tags = var.tags
}

# IAM policy for Lambda execution
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.app_name}-lambda-policy"
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
          var.dynamodb_table_arn,
          "${var.dynamodb_table_arn}/index/*"
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
        Resource = var.sqs_queue_arn
      },
      {
        Effect = "Allow"
        Action = [
          "sts:GetCallerIdentity"
        ]
        Resource = "*"
      }
    ]
  })
}
