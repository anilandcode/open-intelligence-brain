#!/usr/bin/env bash
# a1-retry-launch.sh — Retry A1 launch until capacity opens.
#
# Oracle Cloud A1 capacity comes and goes. This script tries once every
# 30 minutes and exits on success or rate limit.
#
# Usage: ./scripts/a1-retry-launch.sh

set -euo pipefail
export SUPPRESS_LABEL_WARNING=True

TENANCY="ocid1.tenancy.oc1..aaaaaaaaosxt7u5qf7gwvckjkuaakbh4p2zcs6c6gvngmt3u5fdlmh7fa34q"
SUBNET="ocid1.subnet.oc1.ap-singapore-1.aaaaaaaapwsbdgg33odslak3iiowimwpoa7mrmi5op2hndukiqlgtsi22qoa"
IMAGE="ocid1.image.oc1.ap-singapore-1.aaaaaaaaw75ef2chh5goomskvdznqz36cadczqelqvndbqcozc5icyig57za"
AD="WEPM:AP-SINGAPORE-1-AD-1"
SSH_PUB_KEY=$(cat ~/.oci/brain-vm-key.pub)
INTERVAL=1800  # 30 minutes

echo "🔄 A1 Capacity Retry Launcher"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Region: ap-singapore-1"
echo "Shape: 4 OCPU, 24 GB RAM"
echo "Interval: ${INTERVAL}s (30 min)"
echo ""
echo "Press Ctrl+C to stop."
echo ""

attempt=0
while true; do
    attempt=$((attempt + 1))
    echo "[$(date '+%H:%M:%S')] Attempt $attempt — launching..."
    
    RESULT=$(oci compute instance launch \
        --compartment-id "$TENANCY" \
        --availability-domain "$AD" \
        --shape "VM.Standard.A1.Flex" \
        --shape-config '{"ocpus":4,"memoryInGBs":24}' \
        --display-name "digital-brain" \
        --image-id "$IMAGE" \
        --subnet-id "$SUBNET" \
        --metadata "{\"ssh_authorized_keys\":\"$SSH_PUB_KEY\"}" \
        --assign-public-ip true \
        --query 'data.id' --raw-output 2>&1) || true
    
    if echo "$RESULT" | grep -q "ocid1.instance"; then
        echo ""
        echo "✅ SUCCESS! Instance launched."
        echo "ID: $RESULT"
        echo ""
        echo "Waiting for it to start..."
        sleep 60
        VNIC_ID=$(oci compute instance list-vnics --instance-id "$RESULT" --query 'data[0].id' --raw-output 2>/dev/null)
        PUBLIC_IP=$(oci network vnic get --vnic-id "$VNIC_ID" --query 'data."public-ip"' --raw-output 2>/dev/null)
        echo "Public IP: $PUBLIC_IP"
        echo "SSH: ssh -i ~/.oci/brain-vm-key ubuntu@$PUBLIC_IP"
        exit 0
    fi
    
    if echo "$RESULT" | grep -q "Too many requests"; then
        echo "⚠️  Rate limited. Waiting 60 minutes..."
        sleep 3600
        continue
    fi
    
    echo "❌ No capacity. Retrying in 30 minutes..."
    echo "   (Capacity frees in waves — patience pays off)"
    sleep "$INTERVAL"
done