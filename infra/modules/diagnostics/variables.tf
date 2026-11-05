variable "workspace_id" {
  description = "Shared Log Analytics destination."
  type        = string
}
variable "targets" {
  description = "Every deployed resource/subservice supporting Azure diagnostics."
  type        = map(string)
}
