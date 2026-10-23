# Offline installation — Interface Alerting v1.0.2 (git bundle)

For an isolated Production network with no GitHub access. GitHub stays the source of truth: the bundle is a
byte-for-byte copy of tag `v1.0.2` (commit `855cd3286decdd96921335de62dfcee39622bdd9`) with its history.

Needs on the deploy host: `git`, `python3` (3.8+ preferred), PyYAML, HTTPS to the Zabbix frontend. Nothing else.
Inputs to fill (URL, token, user group, media type, interfaces): `docs/CLAUDE-FINAL-PRODUCTION-REVIEW.md` section 5.

Stop at any step that prints `FAIL`, `REVIEW REQUIRED`, `IDENTITY MISMATCH` or `VERIFICATION INCOMPLETE`.

---

## 1. Connected workstation — create the bundle

```bash
git clone https://github.com/jaber717/Zabbix.git Zabbix-src
cd Zabbix-src
git rev-parse 'v1.0.2^{commit}'          # MUST print 855cd3286decdd96921335de62dfcee39622bdd9
git bundle create ../zabbix-alerting-v1.0.2.bundle v1.0.2
cd ..
sha256sum zabbix-alerting-v1.0.2.bundle > zabbix-alerting-v1.0.2.bundle.sha256
cat zabbix-alerting-v1.0.2.bundle.sha256  # record this hash in the change ticket
```

Transfer `zabbix-alerting-v1.0.2.bundle` and `.sha256` to the deploy host by the approved method.

## 2. Deploy host — install (read-only, no approval needed)

```bash
sha256sum -c zabbix-alerting-v1.0.2.bundle.sha256      # MUST print: OK
git clone zabbix-alerting-v1.0.2.bundle Zabbix         # warning "remote HEAD refers to nonexistent ref" is expected
cd Zabbix
git checkout -b prod-local v1.0.2
git rev-parse HEAD                                     # MUST print 855cd3286decdd96921335de62dfcee39622bdd9
cd zabbix-alerting

python3 -c 'import sys, yaml; print(sys.version.split()[0], "PyYAML", yaml.__version__)'
#   missing PyYAML: sudo dnf install -y python3-pyyaml   (from the internal RHEL repo)
#   RHEL 8 (python3 = 3.6): install python39 + python39-pyyaml and prefix every command below with PYTHON=python3.9
python3 -m unittest discover -s tests -t .             # expect: Ran 182 tests ... OK   (skip on Python 3.6)
```

## 3. Deploy host — configure (still no writes to Zabbix)

```bash
cp .env.example .env && chmod 600 .env
vi .env
#   ZABBIX_URL_PRODUCTION=https://<production zabbix frontend>
#   ZABBIX_TOKEN_PRODUCTION=<API token of the dedicated Super admin service user>
#   leave ZABBIX_URL_LAB / ZABBIX_TOKEN_LAB empty
#   internal CA only:  SSL_CERT_FILE=/etc/pki/tls/certs/<company-ca>.pem

vi config/environments/production.yaml
#   zabbix.url_regex: '^https://<production host, dots escaped as \.>(/zabbix)?/?$'
#   and append:
#   alert_action:
#     name: "NETOPS-IaC Interface Alerts"
#     enabled: true
#     usergroups: ["<exact production user group>"]
#     media_type: "<exact production Email media type name>"

vi config/interfaces.production.yaml                   # ISP + P2P interfaces; keep defaults.utilization.enabled: true

./apply.sh --env production --check                    # every interface PASS, then RESULT: PASS
./apply.sh --env production --dry-run > dryrun-$(date +%F).txt; cat dryrun-$(date +%F).txt
```

Send the dry-run file to the approver. **Do not continue without explicit approval.**

## 4. Deploy host — apply (approved change window only)

```bash
./apply.sh --env production --init-identity --confirm production     # once: creates {$NETOPS.ENVIRONMENT}=production
./apply.sh --env production --confirm production                     # last line: verification plan is empty
./apply.sh --env production --dry-run                                # MUST print: No changes required.
python3 scripts/lab_verify_objects.py --env production --config config/interfaces.production.yaml   # RESULT: PASS
```

Then prove e-mail delivery (review section 6, step 9) and collect the evidence in review section 7.

Keep the production configuration under Git on the local branch:

```bash
cd ..
git add zabbix-alerting/config
git -c user.name="<name>" -c user.email="<email>" commit -m "production config v1.0.2"
```

`.env` and `state/` (backups) are git-ignored and never committed.

## 5. Rollback

```bash
cd Zabbix/zabbix-alerting
git log --oneline -- config/interfaces.production.yaml                # pick the last good commit
git checkout <good-commit> -- config/interfaces.production.yaml
./apply.sh --env production --dry-run                                 # review the REMOVE/CHANGE lines
./apply.sh --env production --confirm production
```

Remove everything (first deployment, no good commit yet): set the file to `hosts: {}`, then
`./apply.sh --env production --confirm production --allow-empty`. This leaves the template
`NETOPS Interface Alerting`, the action `NETOPS-IaC Interface Alerts` and the global macro `{$NETOPS.ENVIRONMENT}`;
delete those three in the Zabbix UI for a full uninstall. Every apply first saves `state/backups/production-<time>.json`.

## 6. Future release (example: vX.Y.Z)

Connected workstation:
```bash
cd Zabbix-src && git fetch --tags && git rev-parse 'vX.Y.Z^{commit}'
git bundle create ../zabbix-alerting-vX.Y.Z.bundle vX.Y.Z
cd .. && sha256sum zabbix-alerting-vX.Y.Z.bundle > zabbix-alerting-vX.Y.Z.bundle.sha256
```
Deploy host:
```bash
sha256sum -c zabbix-alerting-vX.Y.Z.bundle.sha256
cd Zabbix
git fetch /path/to/zabbix-alerting-vX.Y.Z.bundle 'refs/tags/vX.Y.Z:refs/tags/vX.Y.Z'
git merge vX.Y.Z                                       # your config commits on prod-local are kept
cd zabbix-alerting && ./apply.sh --env production --dry-run
./apply.sh --env production --confirm production       # only if approved and the dry-run is as expected
```
