output "ids" {
  description = "Dedicated diagnostic setting IDs."
  value       = { for key, setting in azurerm_monitor_diagnostic_setting.this : key => setting.id }
}
