terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.27"
    }
  }
  required_version = ">= 0.14.9"
}

variable "instance_type" {
  type = string
  default = "i3.metal"
  # default = "t2.micro"
}

variable "ami_id" {
  type = string
  default = "ami-00964f8756a53c964"
}

provider "aws" {
  profile = "default"
  region  = "us-east-1"
}

resource "aws_instance" "ALCIB-KVM" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  associate_public_ip_address = "true"
  key_name                    = "alcib-user-prod"
  iam_instance_profile        = "alcib_jenkins_profile"

  tags = {
    Name = "ALCIB-KVM"
  }
}
