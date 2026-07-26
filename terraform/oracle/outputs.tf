output "instance_public_ip" {
  description = "Public IP of the demo VM. Point the Cloudflare A-record for the domain at this IP (DNS-only / grey cloud) so Caddy can obtain the Let's Encrypt certificate."
  value       = oci_core_instance.coav.public_ip
}

output "ssh_private_key_file" {
  description = "Path to the generated SSH private key, or a note when you supplied your own key."
  value       = var.ssh_public_key == "" ? local_sensitive_file.ssh_private_key[0].filename : "(using your own key)"
}

output "ssh_command" {
  description = "Ready-to-run SSH command for the demo VM."
  value       = var.ssh_public_key == "" ? "ssh -i ${path.module}/coav_oracle_ed25519 ubuntu@${oci_core_instance.coav.public_ip}" : "ssh ubuntu@${oci_core_instance.coav.public_ip}"
}
