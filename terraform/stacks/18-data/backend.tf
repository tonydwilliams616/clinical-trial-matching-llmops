terraform {
  backend "s3" {
    bucket       = "ctm-tfstate-359013545044"
    key          = "18-data/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
