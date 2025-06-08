terraform {
    required_providers {
        aws = {
        source  = "hashicorp/aws"
        version = "~> 5.0"
        }
    }
    backend "s3" {
      bucket = "indian-cashcow-backend"
      dynamodb_table="indian-cashcow-tfstate"
      key ="dev/terraform.tfstate"
      region = "us-east-2"
      profile = "ikec-root-admin"
    }
}

provider "aws" {
  region = "us-east-2"
  profile = "ikec-root-admin"
  
}