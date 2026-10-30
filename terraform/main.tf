terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
  }
  backend "s3" {}
}
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.account_id]
  default_tags { tags = { Project = "keyless-cicd", Environment = var.environment, ManagedBy = "Terraform" } }
}
variable "aws_region" { default = "us-east-1" }
variable "account_id" { type = string }
variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Choose dev or prod."
  }
}
locals { name = "keyless-cicd-${var.environment}" }
data "aws_iam_role" "runtime" { name = "${local.name}-runtime" }
data "archive_file" "app" {
  type        = "zip"
  source_file = "${path.module}/../src/app.py"
  output_path = "${path.module}/../.build/app.zip"
}
resource "aws_cloudwatch_log_group" "app" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 7
  #checkov:skip=CKV_AWS_338:Seven-day retention limits costs for this demo.
  #checkov:skip=CKV_AWS_158:AWS-managed encryption avoids a paid customer KMS key for non-sensitive demo logs.
}
resource "aws_lambda_function" "app" {
  #checkov:skip=CKV_AWS_117:This dependency-free demo needs no private network resources.
  #checkov:skip=CKV_AWS_116:Synchronous invocation returns errors directly; there is no async event source.
  #checkov:skip=CKV_AWS_173:Environment contains only the public environment name.
  #checkov:skip=CKV_AWS_272:Code signing requires a separate signing pipeline outside this demo scope.
  #checkov:skip=CKV_AWS_115:Account quota is 10; AWS requires 100 unreserved concurrency to configure reservations.
  function_name                  = local.name
  role                           = data.aws_iam_role.runtime.arn
  runtime                        = "python3.13"
  handler                        = "app.handler"
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256
  memory_size                    = 128
  timeout                        = 5
  reserved_concurrent_executions = -1
  tracing_config { mode = "Active" }
  environment { variables = { ENVIRONMENT = var.environment } }
  depends_on = [aws_cloudwatch_log_group.app]
}
output "function_name" { value = aws_lambda_function.app.function_name }
