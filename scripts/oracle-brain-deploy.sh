#!/usr/bin/env bash
# oracle-brain-deploy.sh — Deploy the Digital Brain to Oracle Cloud Always Free.
#
# Creates a public subnet (if needed), launches an A1 ARM instance,
# installs Docker, deploys the Brain, and returns the public IP.
#
# Usage: ./scripts/oracle-brain-deploy.sh
#
# Only 22, 80 and 443 are opened; the app stays on loopback behind Caddy. See
# deploy/oracle-vm/README.md for the live layout (Caddy, PostgreSQL 18, systemd).

set -euo pipefail

export SUPPRESS_LABEL_WARNING=True

# Oracle Cloud IDs
TENANCY="ocid1.tenancy.oc1..aaaaaaaaosxt7u5qf7gwvckjkuaakbh4p2zcs6c6gvngmt3u5fdlmh7fa34q"
VCN="ocid1.vcn.oc1.ap-singapore-1.amaaaaaankjtkdyawzu4kfsnru4gznid4x7lcveqxgwegixakjqz7z4hm3bq"
IGW="ocid1.internetgateway.oc1.ap-singapore-1.aaaaaaaalqzjhkvuomhbwxj2gadkxl3jjrn2qqpv2xnjz3iymj2ukjpz5oya"
AD="WEPM:AP-SINGAPORE-1-AD-1"
REGION="ap-singapore-1"
SHAPE="VM.Standard.A1.Flex"
COMPARTMENT="$TENANCY"

echo "🧠 Deploying Digital Brain to Oracle Cloud Always Free"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check existing instances
echo "📋 Checking existing instances..."
EXISTING=$(oci compute instance list --compartment-id "$COMPARTMENT" --lifecycle-state RUNNING --query 'length(data)' --raw-output 2>/dev/null || echo "0")
if [ "$EXISTING" -gt "0" ]; then
    echo "⚠️  $EXISTING running instance(s) already. Listing:"
    oci compute instance list --compartment-id "$COMPARTMENT" --lifecycle-state RUNNING --query 'data[*].{name:name, id:id}' --raw-output
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 0; fi
fi

# Step 1: Create public subnet if it doesn't exist
echo "🌐 Setting up public subnet..."
EXISTING_SUBNET=$(oci network subnet list --compartment-id "$COMPARTMENT" --vcn-id "$VCN" --query "data[?\"display-name']=='brain-public'].id | [0]" --raw-output 2>/dev/null || echo "")

if [ -z "$EXISTING_SUBNET" ] || [ "$EXISTING_SUBNET" = "null" ]; then
    # Create route table for public subnet
    echo "  Creating route table..."
    RT_ID=$(oci network route-table create \
        --compartment-id "$COMPARTMENT" \
        --vcn-id "$VCN" \
        --display-name "brain-public-rt" \
        --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" \
        --query 'data.id' --raw-output 2>/dev/null)
    echo "  Route table: $RT_ID"

    # Create security list
    echo "  Creating security list..."
    SL_ID=$(oci network security-list create \
        --compartment-id "$COMPARTMENT" \
        --vcn-id "$VCN" \
        --display-name "brain-public-sl" \
        --ingress-security-rules "[
            {\"protocol\":\"6\",\"source\":\"0.0.0.0/0\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":22,\"max\":22}}},
            {\"protocol\":\"6\",\"source\":\"0.0.0.0/0\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":80,\"max\":80}}},
            {\"protocol\":\"6\",\"source\":\"0.0.0.0/0\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":443,\"max\":443}}}
        ]" \
        --egress-security-rules "[{\"protocol\":\"all\",\"destination\":\"0.0.0.0/0\"}]" \
        --query 'data.id' --raw-output 2>/dev/null)
    echo "  Security list: $SL_ID"

    # Create public subnet
    echo "  Creating public subnet..."
    SUBNET_ID=$(oci network subnet create \
        --compartment-id "$COMPARTMENT" \
        --vcn-id "$VCN" \
        --display-name "brain-public" \
        --availability-domain "$AD" \
        --cidr-block "10.0.1.0/24" \
        --route-table-id "$RT_ID" \
        --security-list-ids "[\"$SL_ID\"]" \
        --prohibit-internet-access false \
        --query 'data.id' --raw-output 2>/dev/null)
    echo "  Public subnet: $SUBNET_ID"
else
    SUBNET_ID="$EXISTING_SUBNET"
    echo "  Public subnet already exists: $SUBNET_ID"
fi

# Step 2: Generate SSH key
echo "🔑 Generating SSH key..."
SSH_KEY_PATH="$HOME/.oci/brain-vm-key"
if [ ! -f "$SSH_KEY_PATH" ]; then
    ssh-keygen -t ed25519 -f "$SSH_KEY_PATH" -N "" -q
    echo "  Generated: $SSH_KEY_PATH"
else
    echo "  Using existing: $SSH_KEY_PATH"
fi
SSH_PUB_KEY=$(cat "${SSH_KEY_PATH}.pub")

# Step 3: Find Ubuntu 24.04 ARM image
echo "📦 Finding Ubuntu 24.04 ARM image..."
IMAGE_ID=$(oci compute image list \
    --compartment-id "$COMPARTMENT" \
    --operating-system "Canonical Ubuntu" \
    --operating-system-version "24.04" \
    --shape "$SHAPE" \
    --sort-by TIMECREATED \
    --sort-order DESC \
    --limit 1 \
    --query 'data[0].id' --raw-output 2>/dev/null)
echo "  Image: $IMAGE_ID"

# Step 4: Launch A1 instance (4 OCPU, 24 GB — full Always Free budget)
echo "🚀 Launching A1 ARM instance (4 OCPU, 24 GB RAM)..."
INSTANCE_ID=$(oci compute instance launch \
    --compartment-id "$COMPARTMENT" \
    --availability-domain "$AD" \
    --shape "$SHAPE" \
    --shape-config '{"ocpus":4,"memoryInGBs":24}' \
    --display-name "digital-brain" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --metadata "{\"ssh_authorized_keys\":\"$SSH_PUB_KEY\"}" \
    --assign-public-ip true \
    --query 'data.id' --raw-output 2>/dev/null)
echo "  Instance: $INSTANCE_ID"

# Step 5: Wait for instance to be running
echo "⏳ Waiting for instance to start..."
for i in $(seq 1 30); do
    STATE=$(oci compute instance get --instance-id "$INSTANCE_ID" --query 'data."lifecycle-state"' --raw-output 2>/dev/null)
    if [ "$STATE" = "RUNNING" ]; then
        echo "  ✅ Instance is RUNNING"
        break
    fi
    echo "  State: $STATE (${i}/30)"
    sleep 10
done

# Step 6: Get public IP
echo "🌐 Getting public IP..."
VNIC_ID=$(oci compute instance list-vnics --instance-id "$INSTANCE_ID" --query 'data[0].id' --raw-output 2>/dev/null)
PUBLIC_IP=$(oci network vnic get --vnic-id "$VNIC_ID" --query 'data."public-ip"' --raw-output 2>/dev/null)
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Digital Brain server deployed!"
echo ""
echo "  Public IP: $PUBLIC_IP"
echo "  SSH: ssh -i $SSH_KEY_PATH ubuntu@$PUBLIC_IP"
echo "  API: behind Caddy on 443 (see deploy/oracle-vm/)"
echo ""
echo "Next steps:"
echo "  1. SSH in: ssh -i $SSH_KEY_PATH ubuntu@$PUBLIC_IP"
echo "  2. Install Docker: curl -fsSL https://get.docker.com | sh"
echo "  3. Clone repo: git clone https://github.com/anilandcode/open-intelligence-brain.git"
echo "  4. Deploy: follow deploy/oracle-vm/README.md (docker-compose.yml is the local dev stack, not production)"
echo ""
echo "Save these:"
echo "  SSH_KEY=$SSH_KEY_PATH"
echo "  INSTANCE_ID=$INSTANCE_ID"
echo "  PUBLIC_IP=$PUBLIC_IP"