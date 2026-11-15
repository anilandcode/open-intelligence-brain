# Oracle VM deployment (live home)

The live Brain runs on one Oracle Always Free A1 VM: Caddy terminates TLS for
`brain.trulyagentic.io` (console + API + `/mcp`) and `bridge.trulyagentic.io`
(the mcp-auth-bridge broker), and PostgreSQL 18 runs on the same box. Cloud Run
(`scripts/deploy-cloud-run.sh`) is the rollback path only.

These files are **templates of that shape**, written from the repository, not
copied from the VM. Reconcile them with what is actually running before relying
on them, then keep them in sync, so the box can be rebuilt from the repo.

| File | Goes to | Purpose |
|---|---|---|
| `Caddyfile` | `/etc/caddy/Caddyfile` | TLS + reverse proxy for both hostnames, security headers |
| `open-brain.service` | `/etc/systemd/system/` | Runs the Brain image bound to loopback |
| `brain.env.example` | `/etc/open-brain/brain.env` (mode 600) | Production settings, no secrets committed |
| `open-brain-backup.service` + `.timer` | `/etc/systemd/system/` | Nightly `scripts/backup-postgres.sh` |

## Network rules

Only 80 and 443 should be reachable from the internet. Port 22 should be limited
to your own address (or closed in favour of the OCI bastion). `scripts/oracle-brain-deploy.sh`
historically opened **8000** to `0.0.0.0/0`; remove that ingress rule from the
`brain-public-sl` security list, and keep the app, the bridge, PostgreSQL (5432)
and the engine (6767/6799) bound to `127.0.0.1` so Caddy is the only way in.

Check from outside the VM:

```bash
for p in 22 80 443 5432 6767 8000 8080; do nc -z -G 3 <vm-ip> $p && echo "$p open" || echo "$p closed"; done
```

## Boot guards

With `BRAIN_PUBLIC_BASE_URL` set to an `https://` origin the app treats itself as
public: it refuses to start on the default owner token, never seeds demo data,
and only lets emails in `BRAIN_BOOTSTRAP_ALLOWED_EMAILS` claim the first-owner
role. It logs any legacy owner grant left by a previous owner token; set
`BRAIN_RETIRE_LEGACY_OWNER_GRANTS=true` for one boot to remove them.

## Restore drill

```bash
createdb brain_restore_check
pg_restore --no-owner --dbname=brain_restore_check /var/backups/open-brain/brain-<stamp>.dump
psql brain_restore_check -c 'select count(*) from knowledge;'
dropdb brain_restore_check
```
