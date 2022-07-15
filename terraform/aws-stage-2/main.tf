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
  default = "t2.micro"
}

variable "ami_id" {
  type = string
  default = "ami-0732b50c88bd647f2"
}

data "template_file" "user_data" {
  template = file("build-tools-on-ec2-userdata.yml")
}

provider "aws" {
  profile = "default"
  region  = "us-east-1"
}

resource "aws_instance" "ALCIB-AWS-STAGE-2" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  associate_public_ip_address = "true"
  key_name                    = "alcib-user-prod"
  iam_instance_profile        = "alcib_jenkins_profile"
  user_data                   = data.template_file.user_data.rendered

  tags = {
    Name = "ALCIB-AWS-STAGE-2"
  }
}
