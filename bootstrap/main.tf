terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers { aws = { source = "hashicorp/aws", version = "~> 6.0" } }
}
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.account_id]
  default_tags { tags = { Project = "keyless-cicd", ManagedBy = "Terraform" } }
}
variable "aws_region" { default = "us-east-1" }
variable "account_id" { type = string }
variable "subject_prefix" { default = "repo:EpicCoder71@57415684/aws-keyless-cicd@1439298585" }
locals {
  environments = toset(["dev", "prod"])
  bucket       = "keyless-cicd-state-${var.account_id}-${var.aws_region}"
}
data "aws_iam_openid_connect_provider" "github" { url = "https://token.actions.githubusercontent.com" }
resource "aws_s3_bucket" "state" {
  bucket = local.bucket
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } }] })
}
resource "aws_iam_role" "runtime" {
  for_each           = local.environments
  name               = "keyless-cicd-${each.key}-runtime"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "runtime" {
  for_each = local.environments
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/keyless-cicd-${each.key}:*" },
    { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" }
  ] })
}
resource "aws_iam_role" "deploy" {
  for_each = local.environments
  name     = "keyless-cicd-${each.key}-deploy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }, Action = "sts:AssumeRoleWithWebIdentity", Condition = { StringEquals = {
    "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub" = "${var.subject_prefix}:environment:${each.key}"
  } } }] })
}
resource "aws_iam_role_policy" "deploy" {
  for_each = local.environments
  role     = aws_iam_role.deploy[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.state.arn, Condition = { StringLike = { "s3:prefix" = ["${each.key}/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.state.arn}/${each.key}/terraform.tfstate" },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.state.arn}/${each.key}/terraform.tfstate.tflock" },
    { Effect = "Allow", Action = ["lambda:CreateFunction", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction", "lambda:ListVersionsByFunction", "lambda:GetFunctionCodeSigningConfig", "lambda:GetPolicy", "lambda:ListTags", "lambda:TagResource", "lambda:UntagResource", "lambda:PutFunctionConcurrency", "lambda:GetFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:InvokeFunction"], Resource = "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:keyless-cicd-${each.key}" },
    { Effect = "Allow", Action = ["iam:GetRole"], Resource = aws_iam_role.runtime[each.key].arn },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = aws_iam_role.runtime[each.key].arn, Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } } },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:DeleteLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"], Resource = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/keyless-cicd-${each.key}:*" },
    { Effect = "Allow", Action = ["logs:DescribeLogGroups"], Resource = "*" }
  ] })
}
output "state_bucket" { value = aws_s3_bucket.state.id }
output "deployment_roles" { value = { for env, role in aws_iam_role.deploy : env => role.arn } }
