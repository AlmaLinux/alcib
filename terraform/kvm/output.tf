output "instance_public_ip" {
  value = aws_instance.ALCIB-KVM.public_ip
}

output "instance_id" {
  value = aws_instance.ALCIB-KVM.id
}