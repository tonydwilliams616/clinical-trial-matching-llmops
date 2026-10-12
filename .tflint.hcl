# tflint configuration, used by CI (`tflint --recursive --config .tflint.hcl`).
# The bundled Terraform ruleset only for now; the AWS ruleset (which needs a
# pinned plugin version) is on the backlog.

config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
