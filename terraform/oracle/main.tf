# COAV free-tier demo on Oracle Cloud Always Free.
# Everything here is Always-Free-eligible: 1x VM.Standard.A1.Flex (within the
# 4 OCPU / 24 GB tenancy cap), a 50 GB boot volume (200 GB free block storage
# cap), VCN + Internet Gateway (no NAT Gateway, no Load Balancer — both would
# either cost money or burn the single free LB slot).

locals {
  # Fall back to the tenancy root compartment when none is given.
  compartment_ocid = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
}

# --- SSH keypair ---------------------------------------------------------------
# When no key is supplied, generate one so `terraform apply` needs zero prior
# SSH setup. The private key also lives in local (gitignored) Terraform state —
# acceptable for a throwaway free-tier VM.
resource "tls_private_key" "ssh" {
  count     = var.ssh_public_key == "" ? 1 : 0
  algorithm = "ED25519"
}

resource "local_sensitive_file" "ssh_private_key" {
  count           = var.ssh_public_key == "" ? 1 : 0
  content         = tls_private_key.ssh[0].private_key_openssh
  filename        = "${path.module}/coav_oracle_ed25519"
  file_permission = "0600"
}

locals {
  ssh_public_key = var.ssh_public_key != "" ? var.ssh_public_key : tls_private_key.ssh[0].public_key_openssh
}

# --- Availability domain -----------------------------------------------------
# Always Free A1 capacity is AD-scoped; we simply take the first AD. If apply
# fails with "Out of host capacity", retry later or try another AD/region.
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# --- OS image ----------------------------------------------------------------
# Latest Canonical Ubuntu 22.04 aarch64 image compatible with the A1 shape.
# Filtering by shape guarantees we get the aarch64 build, not x86_64.
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = local.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# --- Network -----------------------------------------------------------------
resource "oci_core_vcn" "coav" {
  compartment_id = local.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "vcn-coav-free"
  dns_label      = "coavfree"
}

resource "oci_core_internet_gateway" "coav" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.coav.id
  display_name   = "igw-coav-free"
}

resource "oci_core_route_table" "coav" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.coav.id
  display_name   = "rt-coav-free"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.coav.id
  }
}

# SSH + HTTP (Let's Encrypt HTTP-01 / redirect) + HTTPS. Egress open so the
# instance can pull Docker images, apt packages and clone the repo.
resource "oci_core_security_list" "coav" {
  compartment_id = local.compartment_ocid
  vcn_id         = oci_core_vcn.coav.id
  display_name   = "sl-coav-free"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    protocol = "6" # TCP
    source   = "0.0.0.0/0"
    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 80
      max = 80
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }
}

# Regional public subnet — regional (no AD pinned) so the subnet survives
# moving the instance to another AD if capacity requires it.
resource "oci_core_subnet" "coav_public" {
  compartment_id             = local.compartment_ocid
  vcn_id                     = oci_core_vcn.coav.id
  cidr_block                 = "10.0.1.0/24"
  display_name               = "subnet-coav-public"
  dns_label                  = "pub"
  route_table_id             = oci_core_route_table.coav.id
  security_list_ids          = [oci_core_security_list.coav.id]
  prohibit_public_ip_on_vnic = false
}

# --- Compute -----------------------------------------------------------------
resource "oci_core_instance" "coav" {
  compartment_id      = local.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = "coav-free-demo"
  shape               = "VM.Standard.A1.Flex"

  # Flex shape: OCPUs/memory are set here, not implied by the shape name.
  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 50
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.coav_public.id
    assign_public_ip = true
    hostname_label   = "coav"
  }

  # cloud-init does the whole app bootstrap: Docker, git clone, image builds,
  # docker compose up. See cloud-init.yaml.tftpl.
  metadata = {
    ssh_authorized_keys = local.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
      domain     = var.domain
      repo_url   = var.repo_url
      git_branch = var.git_branch
    }))
  }

  # A1 free capacity is scarce; don't recreate the instance just because a
  # newer Ubuntu image was published.
  lifecycle {
    ignore_changes = [source_details[0].source_id]
  }
}
