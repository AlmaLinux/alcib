terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.27"
    }
  }

  required_version = ">= 0.14.9"
}

provider "aws" {
  profile = "default"
  region  = "us-east-1"
}

resource "aws_iam_role" "alcib_jenkins_role" {
  name = "alcib_jenkins_role"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF

  tags = {
    tag-key = "tag-value"
  }
}

resource "aws_iam_instance_profile" "alcib_jenkins_profile" {
  name = "alcib_jenkins_profile"
  role = aws_iam_role.alcib_jenkins_role.name
}

resource "aws_iam_role_policy" "alcib_jenkins_policy" {
  name = "alcib_jenkins_policy"
  role = aws_iam_role.alcib_jenkins_role.id

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
            "Sid": "VisualEditor1",
            "Effect": "Allow",
            "Action": "s3:*",
            "Resource": [
                "arn:aws:s3:::alcib/*",
                "arn:aws:s3:::alcib",
                "arn:aws:s3:::alcib-dev/*",
                "arn:aws:s3:::alcib-dev"
            ]
        }
  ]
}
EOF
}
