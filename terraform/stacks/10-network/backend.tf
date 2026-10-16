terraform {
  backend "s3" {
    bucket       = "ctm-tfstate-359013545044"
    key          = "10-network/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
