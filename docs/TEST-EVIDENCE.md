# Test evidence

## 0. Test capability inventory

Observed 2026-09-13 on the read-only source/staging host:

| Capability | Observed state |
|---|---|
| Test hostname | `netbox-dev` |
| OS | `Red Hat Enterprise Linux release 9.6 (Plow)` |
| Architecture | `x86_64` |
| Disposable clean RHEL 9.6 VM | UNAVAILABLE — Proxmox inventory contained no guest identified and approved for this purpose. |
| Host may be rebooted | NO — it is the active source system. |
| RHEL repository/subscription content | AVAILABLE — privileged read returned BaseOS and AppStream pinned to 9.6; Simple Content Access reported content access. |
| `repo.zabbix.com` | AVAILABLE — pinned 7.0 repodata returned HTTP 200. |
| EPEL | UNAVAILABLE/UNUSED — no EPEL repository was visible; the lock has zero EPEL packages. |
| Suitable real SNMP device | UNAVAILABLE — known lab objects use intentionally fake/non-routable addresses. |
| Real Huawei device | UNAVAILABLE. |
| Real FortiGate device | UNAVAILABLE. |

Commands (read-only, useful output trimmed):

```bash
hostname -f; cat /etc/redhat-release; uname -m
sudo -n subscription-manager status
sudo -n subscription-manager repos --list-enabled
dnf repolist; dnf repolist --all
curl -L -sS -o /dev/null -w '%{http_code}' \
  https://repo.zabbix.com/zabbix/7.0/rhel/9/x86_64/repodata/repomd.xml
```

Results: hostname/OS/architecture as above; BaseOS and AppStream repository IDs
were enabled; EPEL match count was zero; Zabbix repodata returned `200`.

## 1. Offline bundle staging — PASS

Environment: subscribed RHEL 9.6 x86_64 staging context, 2026-09-01.

```bash
RUN_ID=m1-accepted-build1 OUTPUT_DIR="$PWD/build/out/m1-accepted-build1" UPDATE_LOCK=1 build/build.sh
RUN_ID=m1-accepted-build2 OUTPUT_DIR="$PWD/build/out/m1-accepted-build2" build/build.sh
build/compare-builds.sh build/out/m1-accepted-build1 build/out/m1-accepted-build2
```

Observed: each clean-root build resolved and signature-verified 313 RPMs; local
only installs and module checks passed; the second build matched the lock,
module metadata, package provenance/checksums, allow-list, and repository bytes.
The accepted artifact was re-hashed on 2026-09-13 with:

```powershell
Get-FileHash -Algorithm SHA256 dist\m1-accepted-build2\zabbix-rhel96-offline-1.0.0-build1.tar.gz
```

The result matched the accepted recorded SHA-256. The RPM payload and raw
source-system logs are deliberately not copied into this Git repository.

## 2. Official template presence and structure — PASS

Environment: source Zabbix 7.0.30 API, read-only queries, 2026-09-13.

```bash
ssh <source-host> "sudo -n python3 -" < sanitized-template-query.py
```

The query decrypted the already configured Admin credential only inside the
remote process, never printed it, called `template.get`, `item.get`,
`discoveryrule.get`, `itemprototype.get`, and `triggerprototype.get`, then
discarded authentication state. Observed:

| Template | Items | Discovery rules | Item prototypes | Trigger prototypes |
|---|---:|---:|---:|---:|
| Huawei VRP by SNMP | 12 | 5 | 18 | 13 |
| FortiGate by SNMP | 53 | 9 | 75 | 13 |

Huawei discovery included MPU, entity, fan, network interface, and EtherLike
rules. Interface prototypes covered state, speed, traffic, errors, and discards.
FortiGate discovery included interfaces, CPU, HA, sensors, SD-WAN health, VDOM,
VPN tunnel, and wireless. No custom template was imported.

## 3. Release static validation — PASS

Environment: clean Windows release worktree plus read-only RHEL parser check,
2026-09-14.

```bash
PYTHON_BIN=<bundled-python> tests/installer/run_static_tests.sh
python3 scripts/repository-scan.py
ANSIBLE_CONFIG=ansible.cfg ansible-playbook --syntax-check \
  -i inventory/hosts.yml playbooks/site.yml
ANSIBLE_CONFIG=ansible.cfg ansible-playbook --syntax-check \
  -i inventory/hosts.yml playbooks/verify.yml
```

Observed: 29 installer/helper tests and 30 reconciler tests passed; every shell
script passed `bash -n`; all Python parsed as Python 3.9; installer source and
offline-DNF policies passed; both playbooks passed Ansible syntax parsing; the
65-entry installer checksum manifest passed. The deterministic scan reviewed
121 release files and found no
forbidden payload, private-key header, recognized token shape, RFC1918 address,
lab device record, or populated `.env.example` value.

The required bootstrap secret was also searched as an in-memory fixed string
using PowerShell `Select-String -SimpleMatch`; the value was intentionally not
placed in the command transcript or output. Result: zero matches. Generic
password/token assignment candidates were reviewed and were limited to variable
flow, protected standard-input reads, macro placeholders, and test assertions.

The 29-test result includes runtime-secret regressions. They supply a
synthetic password from a file outside the release tree, proves an absent value
passes, then places the same value in a release file and proves the scan fails
closed and prove shell metacharacters remain literal data through the renderer.
The result also includes regressions for stock host prototypes, prototype
inventory, and the exact disabled stock network-discovery rule and check.
It also keeps the fatal-log exception limited to the two observed graceful
Zabbix alert-pipe shutdown messages; all other priority 0..3 entries fail.
The actual deployment-password absence check is executed from the protected
runtime configuration by both `install.sh` and `verify.sh`; its value is never
printed, hashed, or placed in an argument.

## 3.1 Admin authentication verifier — PASS

Environment: existing source Zabbix 7.0.30, 2026-09-14. The release verifier was
streamed to a temporary directory, the already encrypted credential was piped
from `systemd-creds` to standard input, and the temporary directory was removed.

```bash
systemd-creds decrypt --name=zabbix-password <encrypted-credential> - |
  python3 verify_admin_api.py --scheme https --server-name <source-name> \
  --port <source-port> --ca-file <trusted-ca>
```

Observed sanitized result: configured Admin login accepted, API session logged
out, and factory credential rejected. No password, authentication token, or
credential content was printed. This validates the helper and current password
policy, not a fresh installation.

## 4. Runtime qualification

| Test | Status | Reason |
|---|---|---|
| Clean database | UNTESTED | No approved disposable RHEL 9.6 VM. |
| Clean install | UNTESTED | No approved disposable RHEL 9.6 VM. |
| Installer rerun | UNTESTED | No approved disposable RHEL 9.6 VM. |
| Reboot persistence | UNTESTED | Source system may not be rebooted. |
| SELinux/AVC behavior of this release | UNTESTED | Requires clean target execution. |
| `verify.sh` end to end | UNTESTED | Requires installed clean target. |
| Huawei live SNMP collection | UNTESTED | No real/suitable Huawei endpoint. |
| FortiGate live SNMP collection | UNTESTED | No real/suitable FortiGate endpoint. |

These critical runtime omissions force the overall verdict
`FAIL — CRITICAL TEST UNTESTED` and prohibit publication to `main`.
