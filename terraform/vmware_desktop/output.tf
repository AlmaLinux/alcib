output "instance_public_ip" {
  value = aws_instance.ALCIB-VMWare.public_ip
}

output "instance_id" {
  value = aws_instance.ALCIB-VMWare.id
}