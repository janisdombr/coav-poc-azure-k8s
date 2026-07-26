# Optional Cloudflare DNS automation. With the default manage_dns = false the
# record has count 0 and the provider makes no API calls, so an empty token is
# fine for the manual-DNS path.
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Grey cloud (proxied = false) is required for the initial Let's Encrypt
# HTTP-01 issuance — Caddy must receive ports 80/443 directly.
resource "cloudflare_record" "coav" {
  count   = var.manage_dns ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = var.domain
  type    = "A"
  content = oci_core_instance.coav.public_ip
  proxied = false
  ttl     = 60
}
