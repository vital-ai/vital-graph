#!/usr/bin/env bash
# scratch_stack.sh — the vg test stack on a temporary EC2 instance, then gone.
#
# For runs the laptop can't do well (a swapping Mac, a busy Docker VM): one private
# instance, the same docker-compose test stack on the same dataset volumes, torn down
# when done. Nothing here is shared or long-lived except the dataset snapshots in S3,
# the security group and the key pair.
#
#   scratch_stack.sh up [volume ...]   start an instance, sync the working tree, restore
#                                      the volumes (default: vgtest_core) from S3, build
#                                      and start the test stack on the first volume
#   scratch_stack.sh resume [volume]   finish an `up` that stopped partway
#   scratch_stack.sh sync              re-sync the working tree and rebuild the app
#   scratch_stack.sh run <cmd ...>     run a command in the repo on the instance
#   scratch_stack.sh ssh               interactive shell
#   scratch_stack.sh status            this script's instances
#   scratch_stack.sh down              terminate this script's instance
#   scratch_stack.sh sweep             terminate EVERY instance tagged Project=vg-scratch
#   scratch_stack.sh push-snapshot <volume>
#                                      upload $VG_SNAPSHOT_DIR/<volume>.tar.zst (+ .json)
#
# Safety, in layers:
#   - the instance shuts itself down after VG_SCRATCH_TTL_MIN (default 180) minutes,
#     and shutdown TERMINATES it (its disk is deleted with it);
#   - `down` / `sweep` terminate by tag;
#   - SSH is open only to this machine's current public IP;
#   - the AWS profile (default `vg-scratch`) is an IAM user that can only start,
#     stop and terminate instances tagged Project=vg-scratch and read/write one bucket.
#
# Secrets: the instance gets NO `.env`. It gets a generated one holding only the
# test stack's non-secret settings. `up --with-openai-key` also copies
# OPENAI_API_KEY (needed only by the vector-provider tests).
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE="${VG_SCRATCH_PROFILE:-vg-scratch}"
REGION="${VG_SCRATCH_REGION:-us-east-1}"
TYPE="${VG_SCRATCH_TYPE:-r8g.2xlarge}"          # arm64, like the laptop's snapshots
DISK_GB="${VG_SCRATCH_DISK_GB:-300}"
TTL_MIN="${VG_SCRATCH_TTL_MIN:-180}"
STATE="${VG_SCRATCH_STATE:-$HOME/.vg-scratch}"
SNAPDIR="${VG_SNAPSHOT_DIR:-$HOME/vg-snapshots}"
TAG=vg-scratch
REMOTE_DIR=vital-graph

export AWS_PROFILE="$PROFILE" AWS_REGION="$REGION" AWS_PAGER=""
die() { echo "scratch_stack: $*" >&2; exit 1; }
log() { echo "scratch_stack: $*" >&2; }

bucket() { echo "vg-scratch-$(aws sts get-caller-identity --query Account --output text)"; }
key()    { echo "$STATE/id_ed25519"; }
ip()     { cat "$STATE/ip" 2>/dev/null || die "no instance (run 'up')"; }
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$STATE/known_hosts"
          -o ConnectTimeout=10 -o ServerAliveInterval=30)
rssh()   { ssh -i "$(key)" "${SSH_OPTS[@]}" "ubuntu@$(ip)" "$@"; }

# A long remote step runs DETACHED on the instance, logging to ~/scratch-<name>.log,
# and is polled with short SSH calls: a dropped connection (a laptop network blip)
# must not kill a 10-minute build or restore halfway. Polling retries through drops.
rlong() {   # rlong <name> <shell command>
  local name="$1" cmd="$2" st=""
  rssh "rm -f ~/scratch-$name.rc; nohup setsid bash -c '$cmd; echo \$? > ~/scratch-$name.rc' \
        > ~/scratch-$name.log 2>&1 < /dev/null &"
  while :; do
    sleep 15
    st="$(rssh "cat ~/scratch-$name.rc 2>/dev/null || echo running" 2>/dev/null || echo unreachable)"
    case "$st" in running|unreachable) continue ;; esac
    break
  done
  rssh "tail -5 ~/scratch-$name.log" || true
  [ "$st" = 0 ] || die "remote step '$name' failed (exit $st); see ~/scratch-$name.log on the instance"
}

ensure_key() {
  mkdir -p "$STATE"; chmod 700 "$STATE"
  [ -f "$(key)" ] || ssh-keygen -q -t ed25519 -N "" -C vg-scratch -f "$(key)"
  aws ec2 describe-key-pairs --key-names vg-scratch >/dev/null 2>&1 ||
    aws ec2 import-key-pair --key-name vg-scratch \
      --public-key-material "fileb://$(key).pub" \
      --tag-specifications "ResourceType=key-pair,Tags=[{Key=Project,Value=$TAG}]" >/dev/null
}

ensure_sg() {   # prints the group id; SSH from this machine's IP only
  local sg myip
  sg="$(aws ec2 describe-security-groups --filters Name=group-name,Values=vg-scratch \
        --query 'SecurityGroups[0].GroupId' --output text)"
  if [ "$sg" = "None" ] || [ -z "$sg" ]; then
    sg="$(aws ec2 create-security-group --group-name vg-scratch \
          --description "vg scratch stack: SSH from one IP" \
          --tag-specifications "ResourceType=security-group,Tags=[{Key=Project,Value=$TAG}]" \
          --query GroupId --output text)"
  fi
  myip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
  local old; old="$(aws ec2 describe-security-groups --group-ids "$sg" \
        --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`].IpRanges[].CidrIp' --output text)"
  for c in $old; do
    [ "$c" = "$myip/32" ] || aws ec2 revoke-security-group-ingress --group-id "$sg" \
        --protocol tcp --port 22 --cidr "$c" >/dev/null
  done
  case " $old " in *" $myip/32 "*) ;; *)
    aws ec2 authorize-security-group-ingress --group-id "$sg" --protocol tcp --port 22 \
        --cidr "$myip/32" >/dev/null ;; esac
  echo "$sg"
}

user_data() {
  cat <<EOF
#!/bin/bash
set -eux
shutdown -h +$TTL_MIN "vg-scratch TTL"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 docker-buildx zstd rsync jq
usermod -aG docker ubuntu
touch /var/lib/cloud/vg-scratch-ready
EOF
}

sync_tree() {
  log "syncing the working tree (tracked + untracked, not ignored)"
  git ls-files -co --exclude-standard -z |
    rsync -a --from0 --files-from=- -e "ssh -i $(key) ${SSH_OPTS[*]}" ./ "ubuntu@$(ip):$REMOTE_DIR/"
}

write_env() {   # the stack's non-secret settings only
  local vol="$1" with_key="$2" envf; envf="$(mktemp)"
  {
    echo "VGTEST_PGDATA=$vol"
    grep -E '^(VITALGRAPH_(ENTITY|AGENT)_REGISTRY_VECTOR_PROVIDER|VG_MAINTENANCE_EXCLUDE_SPACES|VG_TEST_SHARED_BUFFERS)=' .env 2>/dev/null || true
    [ "$with_key" = 1 ] && grep -E '^OPENAI_API_KEY=' .env || true
  } > "$envf"
  scp -q -i "$(key)" "${SSH_OPTS[@]}" "$envf" "ubuntu@$(ip):$REMOTE_DIR/.env"
  rm -f "$envf"
}

restore_volume() {   # S3 snapshot -> docker volume on the instance (vg_volume.sh restore)
  local vol="$1" b url urlj; b="$(bucket)"
  aws s3api head-object --bucket "$b" --key "snapshots/$vol.tar.zst" >/dev/null 2>&1 ||
    die "no s3://$b/snapshots/$vol.tar.zst (scratch_stack.sh push-snapshot $vol)"
  url="$(aws s3 presign "s3://$b/snapshots/$vol.tar.zst" --expires-in 3600)"
  urlj="$(aws s3 presign "s3://$b/snapshots/$vol.tar.zst.json" --expires-in 3600)"
  log "restoring volume $vol from S3"
  rlong "restore-$vol" "set -e; mkdir -p ~/vg-snapshots; cd ~/vg-snapshots
        curl -fsS -o $vol.tar.zst.json \"$urlj\" || rm -f $vol.tar.zst.json
        curl -fsS -o $vol.tar.zst \"$url\"
        cd ~/$REMOTE_DIR && ./scripts/vg_volume.sh restore ~/vg-snapshots/$vol.tar.zst $vol
        rm -f ~/vg-snapshots/$vol.tar.zst"
}

compose_up() {
  log "building and starting the test stack"
  rlong compose-up "cd ~/$REMOTE_DIR && docker compose -f docker-compose.test.yml \
        -f docker-compose.test.persist.yml up -d --build --wait"
}

cmd_up() {
  local with_key=0 vols=()
  for a in "$@"; do
    case "$a" in --with-openai-key) with_key=1 ;; *) vols+=("$a") ;; esac
  done
  [ ${#vols[@]} -gt 0 ] || vols=(vgtest_core)
  [ -f "$STATE/instance" ] && aws ec2 describe-instances --instance-ids "$(cat "$STATE/instance")" \
      --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null |
      grep -qE 'pending|running' && die "instance $(cat "$STATE/instance") is up; 'down' it first"
  ensure_key
  local sg ami id
  sg="$(ensure_sg)"
  ami="$(aws ssm get-parameter --name \
        /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
        --query Parameter.Value --output text)"
  log "starting $TYPE ($DISK_GB GB, terminates itself after $TTL_MIN min)"
  id="$(aws ec2 run-instances --image-id "$ami" --instance-type "$TYPE" \
        --key-name vg-scratch --security-group-ids "$sg" \
        --instance-initiated-shutdown-behavior terminate \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Iops=6000,Throughput=500,DeleteOnTermination=true}" \
        --user-data "$(user_data)" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Project,Value=$TAG},{Key=Name,Value=vg-scratch}]" \
                             "ResourceType=volume,Tags=[{Key=Project,Value=$TAG}]" \
        --query 'Instances[0].InstanceId' --output text)"
  echo "$id" > "$STATE/instance"
  aws ec2 wait instance-running --instance-ids "$id"
  aws ec2 describe-instances --instance-ids "$id" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text > "$STATE/ip"
  log "instance $id at $(ip); waiting for setup"
  local i; for i in $(seq 1 90); do
    rssh test -f /var/lib/cloud/vg-scratch-ready 2>/dev/null && break; sleep 10
  done
  rssh test -f /var/lib/cloud/vg-scratch-ready || die "setup did not finish; see /var/log/cloud-init-output.log"
  sync_tree
  write_env "${vols[0]}" "$with_key"
  # Images first: the restore reads the cluster state with the test Postgres image.
  log "building the images"
  rlong build "cd ~/$REMOTE_DIR && docker compose -f docker-compose.test.yml \
        -f docker-compose.test.persist.yml build"
  for v in "${vols[@]}"; do restore_volume "$v"; done
  compose_up
  log "up: $(ip), stack on ${vols[0]}; 'down' when done (auto-terminates at TTL)"
}

cmd_sync() { sync_tree; rlong sync "cd ~/$REMOTE_DIR && docker compose -f docker-compose.test.yml \
               -f docker-compose.test.persist.yml up -d --build --wait vitalgraph"; }

# Resume an `up` that stopped partway (e.g. on a dropped connection): every step is
# idempotent or skipped when done.
cmd_resume() {
  local vol="${1:-vgtest_core}"
  sync_tree
  rssh "test -f ~/$REMOTE_DIR/.env" || write_env "$vol" 0
  rlong build "cd ~/$REMOTE_DIR && docker compose -f docker-compose.test.yml \
        -f docker-compose.test.persist.yml build"
  rssh "docker volume inspect $vol >/dev/null 2>&1" || restore_volume "$vol"
  compose_up
  log "up: $(ip), stack on $vol"
}
cmd_run()  { local q; q="$(printf '%q ' "$@")"; rssh "cd ~/$REMOTE_DIR && $q"; }

cmd_status() {
  aws ec2 describe-instances --filters "Name=tag:Project,Values=$TAG" \
      Name=instance-state-name,Values=pending,running,stopping,stopped \
      --query 'Reservations[].Instances[].[InstanceId,InstanceType,State.Name,PublicIpAddress,LaunchTime]' \
      --output text
}

terminate() {
  [ $# -gt 0 ] || { log "nothing to terminate"; return; }
  aws ec2 terminate-instances --instance-ids "$@" >/dev/null
  log "terminating $*"
  aws ec2 wait instance-terminated --instance-ids "$@"
  log "terminated"
}
cmd_down()  { [ -f "$STATE/instance" ] || die "no instance recorded"; terminate "$(cat "$STATE/instance")"
              rm -f "$STATE/instance" "$STATE/ip"; }
cmd_sweep() { local ids; ids="$(cmd_status | cut -f1)"; terminate $ids; rm -f "$STATE/instance" "$STATE/ip"; }

cmd_push_snapshot() {
  local vol="$1" b; b="$(bucket)"
  [ -f "$SNAPDIR/$vol.tar.zst" ] || die "no $SNAPDIR/$vol.tar.zst (scripts/vg_volume.sh snapshot $vol)"
  aws s3 cp "$SNAPDIR/$vol.tar.zst" "s3://$b/snapshots/$vol.tar.zst" --only-show-errors
  [ -f "$SNAPDIR/$vol.tar.zst.json" ] &&
    aws s3 cp "$SNAPDIR/$vol.tar.zst.json" "s3://$b/snapshots/$vol.tar.zst.json" --only-show-errors
  log "pushed $vol to s3://$b/snapshots/"
}

case "${1:-}" in
  up)     shift; cmd_up "$@" ;;
  sync)   cmd_sync ;;
  resume) shift; cmd_resume "$@" ;;
  run)    shift; [ $# -gt 0 ] || die "usage: run <cmd ...>"; cmd_run "$@" ;;
  ssh)    rssh ;;
  status) cmd_status ;;
  down)   cmd_down ;;
  sweep)  cmd_sweep ;;
  push-snapshot) [ $# -eq 2 ] || die "usage: push-snapshot <volume>"; cmd_push_snapshot "$2" ;;
  *) sed -n '2,32p' "$0"; exit 1 ;;
esac
