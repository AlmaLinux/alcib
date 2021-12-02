output "instance_public_ip" {
  value = aws_instance.ALCIB-HyperV.public_ip
}

output "instance_id" {
  value = aws_instance.ALCIB-HyperV.id
}