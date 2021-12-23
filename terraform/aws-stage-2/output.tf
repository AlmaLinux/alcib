output "instance_public_ip" {
  value = aws_instance.ALCIB-AWS-STAGE-2.public_ip
}

output "instance_id" {
  value = aws_instance.ALCIB-AWS-STAGE-2.id
}