output "nat_gateway_id" {
  description = "NAT gateway ID."
  value       = aws_nat_gateway.this.id
}

output "nat_public_ip" {
  description = "Public IP that private-subnet traffic leaves from - useful for allow-lists."
  value       = aws_eip.nat.public_ip
}
