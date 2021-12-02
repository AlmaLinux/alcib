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

resource "aws_instance" "ALCIB-KVM" {
  ami                         = "ami-00964f8756a53c964"
  instance_type               = "i3.metal"
  associate_public_ip_address = "true"
  key_name                    = "alcib-user-prod"
  iam_instance_profile        = "alcib_jenkins_profile"

  tags = {
    Name = "ALCIB-KVM"
  }
}
