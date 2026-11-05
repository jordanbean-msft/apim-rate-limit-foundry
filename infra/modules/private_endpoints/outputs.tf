output "ids" {
  description = "Policy-DNS-managed endpoint IDs."
  value       = { for key, endpoint in azurerm_private_endpoint.this : key => endpoint.id }
}
