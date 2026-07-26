# OCI API auth (from `oci setup config`, usually ~/.oci/config values).
variable "tenancy_ocid" {
  description = "OCID of the tenancy (root compartment)."
  type        = string
}

variable "user_ocid" {
  description = "OCID of the API user."
  type        = string
}

variable "fingerprint" {
  description = "Fingerprint of the API signing key."
  type        = string
}

variable "private_key_path" {
  description = "Path to the API signing private key (PEM)."
  type        = string
}

variable "region" {
  description = "OCI region identifier, e.g. eu-frankfurt-1. Always Free A1 capacity varies per region."
  type        = string
}

# Empty default means "use the tenancy root compartment" (resolved in main.tf).
variable "compartment_ocid" {
  description = "Compartment for all resources. Defaults to the tenancy OCID (root compartment)."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key material (contents of ~/.ssh/id_ed25519.pub or similar) for the ubuntu user. Leave empty to have Terraform generate an ED25519 keypair (private key written locally to the file named in the ssh_private_key_file output)."
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "Git repository URL to clone on the instance (assumed public)."
  type        = string
  default     = "https://github.com/janisdombr/coav-poc-azure-k8s.git"
}

variable "git_branch" {
  description = "Git branch to deploy."
  type        = string
  default     = "free-tier-mock"
}

variable "domain" {
  description = "Public domain for the demo; Caddy obtains a Let's Encrypt cert for it."
  type        = string
  default     = "coav.dombrovski.lv"
}

variable "manage_dns" {
  description = "Set true to have Terraform create the Cloudflare A record, otherwise you point DNS manually."
  type        = bool
  default     = false
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with Zone:DNS:Edit on the zone. Only needed when manage_dns = true."
  type        = string
  default     = ""
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID containing the domain. Only needed when manage_dns = true."
  type        = string
  default     = "c59b56eb229157f3fa2740e0c7e526d8"
}

# Always Free allows up to 4 OCPUs / 24 GB total across all A1 instances.
# 2 OCPU / 12 GB leaves headroom and comfortably fits Maven + Docker builds.
variable "instance_ocpus" {
  description = "OCPUs for the A1.Flex instance (Always Free total cap: 4)."
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Memory in GB for the A1.Flex instance (Always Free total cap: 24)."
  type        = number
  default     = 12
}
