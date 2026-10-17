output "endpoint_ids" {
  description = "Interface endpoint IDs by service."
  value       = { for k, e in aws_vpc_endpoint.interface : k => e.id }
}

output "endpoint_security_group_id" {
  description = "Security group on the interface endpoints - later stacks narrow access with it."
  value       = aws_security_group.endpoints.id
}
