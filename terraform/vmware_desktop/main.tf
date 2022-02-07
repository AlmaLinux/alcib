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

resource "aws_instance" "ALCIB-VMWare" {
  ami                         = "ami-008d657511f08ef08"
  instance_type               = "i3.metal"
  associate_public_ip_address = "true"
  key_name                    = "alcib-user-prod"
  iam_instance_profile        = "alcib_jenkins_profile"

  tags = {
    Name = "ALCIB-VMWare"
  }

  root_block_device {
    volume_size = "100"
    volume_type = "gp2"
  }
}
