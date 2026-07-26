# COAV demo on Oracle Cloud Always Free

Deploys the COAV GUI in **mock mode** (built-in flight simulator + backend
camera replay) to a single Oracle Cloud **Always Free** ARM VM. No Azure, no
Event Hub, no emulator — monthly cost: **0 EUR** as long as everything stays
inside the Always Free limits (it does, see notes below).

Stack on the VM: Docker Compose with `backend` (Spring Boot, `mock` profile,
`COAV_MOCKCAMERA_ENABLED=true`), `frontend` (nginx + Vue build, same-origin
`BACKEND_URL=""`), and `caddy` (TLS via Let's Encrypt, reverse proxy for
`/api/*`, `/ws/*` and the SPA).

## Prerequisites

- An Oracle Cloud account (free tier is enough).
- OpenTofu or Terraform >= 1.5 (`tofu` is a drop-in for every `terraform` command below).
- An SSH key is **optional** — Terraform generates an ED25519 keypair if you don't supply your own.

### Get your OCIDs

`oci setup config` (next step) prompts for two IDs. Grab them from the OCI Console **Profile** menu
(the avatar, top-right):

- **Tenancy OCID** — Profile → **Tenancy: \<name\>** → on the Tenancy details page, click *Copy* under OCID.
- **User OCID** — Profile → your **Identity domain** / username → on your User details page, click *Copy* under OCID.

### Configure OCI auth

Run the CLI setup, paste the two OCIDs and pick your region when prompted, and let it generate a new
API signing key pair (it writes `~/.oci/config` and the key into `~/.oci/`):

```bash
oci setup config
```

Then upload the generated **public** key so the API key is trusted. When `oci setup config`
finishes it prints a link to the official steps (Oracle docs, *"How to upload the public key"*) —
follow them: Profile menu → **User settings** → **Token and keys** → **Add API Key** → select
**Paste a public key** → paste the contents of `~/.oci/oci_api_key_public.pem` → **Add**.

## Deploy

Generate `terraform.tfvars` straight from the config `oci setup config` just wrote — this reads its
`[DEFAULT]` profile:

```bash
cd terraform/oracle
awk -F'=' '
  /^\[/ { sec = $0 }
  sec == "[DEFAULT]" && /=/ {
    k = $1; v = substr($0, index($0, "=") + 1)
    gsub(/^[ \t]+|[ \t]+$/, "", k); gsub(/^[ \t]+|[ \t]+$/, "", v); m[k] = v
  }
  END {
    printf "tenancy_ocid     = \"%s\"\n", m["tenancy"]
    printf "user_ocid        = \"%s\"\n", m["user"]
    printf "fingerprint      = \"%s\"\n", m["fingerprint"]
    printf "private_key_path = \"%s\"\n", m["key_file"]
    printf "region           = \"%s\"\n", m["region"]
  }
' ~/.oci/config > terraform.tfvars
```

**Optional** — if you want to reuse an existing SSH key instead of the one Terraform
generates, append its public key (change the `.pub` path if you don't use ed25519):

```bash
printf 'ssh_public_key   = "%s"\n' "$(cat ~/.ssh/id_ed25519.pub)" >> terraform.tfvars
```

Without it, `terraform apply` runs with no prompt and generates an ED25519 keypair for you.

`repo_url` and `domain` fall back to the defaults in `variables.tf` (this repo and
`coav.dombrovski.lv`); add them to `terraform.tfvars` only if they differ. Review the generated
file, then apply:

```bash
terraform init
terraform plan
terraform apply
```

SSH in with the command from `terraform output -raw ssh_command` — when Terraform generated
the keypair, the private key is at `terraform/oracle/coav_oracle_ed25519` (gitignored,
chmod 600).

## DNS (Cloudflare)

Take the IP from the Terraform output:

```bash
terraform output instance_public_ip
```

In Cloudflare, create/update the **A record** for `coav.dombrovski.lv`
pointing to that IP, with proxy status **DNS only (grey cloud)** — Caddy must
receive traffic directly on ports 80/443 to pass the Let's Encrypt HTTP
challenge. You can switch to the orange cloud later if desired, after the
cert exists.

## First boot and verification

Cloud-init installs Docker, clones the repo (branch `free-tier-mock`), builds
both images natively on ARM and starts the compose stack. Expect **10–15
minutes** on first boot (the Maven build dominates). Progress log on the VM:
`/var/log/coav-bootstrap.log`. Caddy obtains the TLS certificate within a
minute of DNS resolving to the VM.

Verify:

```bash
curl -s https://coav.dombrovski.lv/api/flights | head -c 300
curl -s https://coav.dombrovski.lv/api/camera-verification | head -c 300
```

Both should return JSON. Then open `https://coav.dombrovski.lv` in a browser —
the map should populate and the WebSocket (`/ws`) should connect (flights move
without page reload).

To inspect the stack over SSH:

```bash
ssh ubuntu@$(terraform output -raw instance_public_ip)
sudo docker compose -f /opt/coav/terraform/oracle/docker-compose.yml ps
sudo docker compose -f /opt/coav/terraform/oracle/docker-compose.yml logs -f caddy
```

## Free-tier notes

- **Main gotcha: "Out of host capacity".** `VM.Standard.A1.Flex` free
  capacity is scarce in popular regions. If `terraform apply` fails with this
  error, retry later (capacity is released continuously), try another
  availability domain, or pick a less busy home region when signing up. The
  config uses 2 OCPU / 12 GB — half of the 4 OCPU / 24 GB Always Free A1 cap.
  Free capacity is allocated per region **and** per availability domain, and
  the home region cannot be changed after signup. Small/newer regions
  (Madrid, Marseille, Milan) are single-AD, so the "try another AD" advice
  does not apply there.
- **Retry loop for A1 capacity.** Capacity is released continuously, so a
  loop that re-runs `apply` every few minutes usually wins within hours:

  ```bash
  until terraform apply -auto-approve; do sleep 180; done
  ```

- **Pay-As-You-Go unlocks capacity while staying €0.** Free-tier-only
  accounts are deprioritized in the Ampere capacity queue — the single
  biggest cause of the error above. Upgrading the billing profile to
  Pay-As-You-Go moves the account to the front of that queue (A1 usually
  launches immediately) **without** losing Always Free: the A1.Flex within
  the 4 OCPU / 24 GB cap is still billed €0, and PAYG accounts are also exempt
  from the 7-day idle-reclamation that can stop free-tier instances — useful
  for a demo that sits idle for weeks. The trade-off: on PAYG the console no
  longer restricts you to free shapes, so anything created *beyond* the
  Always Free caps bills at list price. Guard against it with a budget alert:
  **Billing & Cost Management → Budgets → Create Budget**, target the root
  compartment, threshold €0.01, alert to your email — you get a mail on the
  first cent of paid usage. (The one-time ~€90 card charge shown at upgrade is
  a verification hold, not a real charge; it is released by your bank within a
  few days.)
- **Everything here is Always-Free-eligible**: one A1.Flex instance within
  the cap, a 50 GB boot volume (200 GB free block storage total), VCN +
  Internet Gateway, one public IPv4. No NAT Gateway and no Load Balancer are
  used — the VM is directly on a public subnet and Caddy does the routing.
- Egress is far below the 10 TB/month free allowance for a demo.

## Automate DNS too (optional)

DNS automation is built in but off by default (`manage_dns = false`), so normal
runs never prompt for Cloudflare credentials — with the default you set the
A-record by hand as described in the DNS section above.

Create the API token in Cloudflare: **Manage Account → Account API Tokens → Create a token → Create
Custom Token**. Add a single permission — **DNS → Edit** (the others — Zone, Zone Settings, Zone DNS
Settings, Zone Versioning, Zone Custom Asset — are not needed). Under **Zone Resources** scope it to
**Include → Specific zone → dombrovski.lv**, create it, and copy the token — it is shown only once.

`cloudflare_zone_id` is already set as a default in `variables.tf`, so to automate DNS you only add
to `terraform.tfvars`:

```hcl
manage_dns           = true
cloudflare_api_token = "<token from the step above>"
```

Deploying to a **different domain or Cloudflare account**? Also override `domain` and
`cloudflare_zone_id` (the committed defaults target `dombrovski.lv`); find the Zone ID under that
domain's **Overview → API → Zone ID**:

```hcl
domain             = "coav.example.com"
cloudflare_zone_id = "<your zone id>"
```

Then a single `terraform apply` brings up the VM and the A-record together. The
record is created grey-cloud (`proxied = false`) — required for the initial
Let's Encrypt issuance; you can switch to the orange cloud later if desired.
The API token needs only `Zone:DNS:Edit` on the one zone.
