output "instance_public_ip" {
  value = aws_instance.ALCIB-VirtualBox.public_ip
}

output "instance_id" {
  value = aws_instance.ALCIB-VirtualBox.id
}
