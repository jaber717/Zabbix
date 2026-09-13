# Test evidence

## 0. Test capability inventory

Observed 2026-09-14 across the read-only source/staging host and the authorized
disposable qualification guest:

| Capability | Observed state |
|---|---|
| Test hostname | `ZABBIX-QUAL-RHEL96` (Proxmox VM 150) |
| OS | `Red Hat Enterprise Linux release 9.6 (Plow)` |
| Architecture | `x86_64` |
| Disposable clean RHEL 9.6 VM | AVAILABLE — newly created VM 150 was used only for this qualification. |
| Host may be rebooted | YES — reboot, snapshot, and rollback were explicitly authorized for VM 150. |
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

Observed: 32 installer/helper tests and 30 reconciler tests passed; every shell
script passed `bash -n`; all Python parsed as Python 3.9; installer source and
offline-DNF policies passed; both playbooks passed Ansible syntax parsing; the
66-entry installer checksum manifest passed. The deterministic scan reviewed
122 release files and found no
forbidden payload, private-key header, recognized token shape, RFC1918 address,
lab device record, or populated `.env.example` value.

The required bootstrap secret was also searched as an in-memory fixed string
using PowerShell `Select-String -SimpleMatch`; the value was intentionally not
placed in the command transcript or output. Result: zero matches. Generic
password/token assignment candidates were reviewed and were limited to variable
flow, protected standard-input reads, macro placeholders, and test assertions.

The 32-test result includes runtime-secret regressions. They supply a
synthetic password from a file outside the release tree, prove an absent value
passes, then place the same value in a release file and prove the scan fails
closed and shell metacharacters remain literal data through the renderer.
The result also includes regressions for stock host prototypes, prototype
inventory, and the exact disabled stock network-discovery rule and check.
The fatal-log check uses the current service process's monotonic start boundary,
so intentional prior-process shutdown messages are excluded while every
priority 0..3 entry from the running Zabbix process fails.
Seed mode requires empty history, trends, events, problems, and sessions;
runtime mode permits new stock-host monitoring rows while still requiring the
exact normal-host, user, interface, inventory, token, and discovery identities.
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

## 4. Runtime qualification — PASS

Environment: Proxmox VM 150 (`ZABBIX-QUAL-RHEL96`), RHEL 9.6 x86_64 Minimal,
SELinux Enforcing, 4 vCPU, 8 GiB RAM, and 80 GiB disk. The release tree was the
clean staging commit `850780289ed25293fb96cd64860c8b53013890a8`. Runtime
credentials were supplied only through root-owned mode `0600` configuration;
they were not printed, hashed, placed in arguments, or added to Git evidence.

### 4.1 Connected clean install — PASS

```bash
git status --short --branch
git rev-parse HEAD
sudo /opt/Zabbix/install.sh
sudo /opt/Zabbix/verify.sh
```

Useful output: the initial installer recap was `ok=162 changed=54 failed=0`
followed by `PASS: installation completed`. The independent verifier returned
`ok=31 changed=0 failed=0` and `ZABBIX DEPLOYMENT VERIFICATION: PASS`.
The verifier proved the exact package lock, PostgreSQL 16, Zabbix 7.0.30,
enabled and active services, frontend response, listening ports, firewalld,
SELinux Enforcing, relevant AVC absence, current-process fatal-log absence,
Admin authentication, rejection of the factory credential, official network
templates, and file-only local repository behavior.

### 4.2 Unchanged installer rerun — PASS

The interrupted/nonexistent rerun was explicitly marked NOT COUNTED. One new
formal rerun was started from the beginning on the current installed state,
without changing the configuration or commit:

```bash
sudo /opt/Zabbix/install.sh
sudo /opt/Zabbix/verify.sh
```

Useful output: installer recap `ok=138 changed=2 failed=0`; independent verifier
recap `ok=31 changed=0 failed=0`. The database OID, schema version, release
state, user set, repository definition, and services remained valid. No schema,
user, repository, or integration duplication was observed.

### 4.3 Connected reboot and clean database — PASS

```bash
cat /proc/sys/kernel/random/boot_id
sudo systemctl reboot
sudo /opt/Zabbix/verify.sh
sudo -u postgres /usr/libexec/zabbix-offline/assert-clean-database \
  --database zabbix --mode runtime
```

The connected boot ID changed from
`866eacca-0609-431a-ab1d-4301fc04dd84` to
`5a23c120-fb03-48cb-bade-a66e2d5fe437`. The post-boot verifier passed all 31
tasks. The initial pre-service seed guard had required empty history, trends,
events, problems, and sessions. The post-start runtime guard returned
`PASS: clean Zabbix database (runtime)`: the only normal host was the stock
`Zabbix server`; the only users were `Admin` and `guest`; API tokens,
discovered hosts, and discovered services were all zero; database version was
`7000000|7000030`. No migrated monitored host, integration user, token,
history, discovery inventory, or other source-system state was introduced.

### 4.4 Destructive database safety — PASS

Environment: a powered-off `connected-qualified` snapshot of VM 150 was taken
before this test. A single disabled sentinel host was inserted into only the
disposable qualification database.

```bash
sudo /opt/Zabbix/install.sh
```

Useful output: the installer exited `2` with
`FAIL: clean database policy: unexpected real host set`. Database OID `16385`,
the sentinel, the stock host, and database version `7000000|7000030` were all
retained. The guest was rolled back to the clean qualified snapshot; the
sentinel was absent after restore and the 31-task verifier passed. The installer
did not drop, reinitialize, wipe, or silently reset the database.

### 4.5 Airgapped clean install and reboot — PASS

Environment: VM 150 was rolled back to its fresh `clean-rhel96` snapshot. The
accepted 313-RPM artifact was transferred from operator-local storage. Its
SHA-256 matched
`dbcd9a1185a21f1bc44bff356f06088ac63d77a5bb8fe539ad573280d9cef42b`,
and its internal `SHA256SUMS` passed. No RPM was obtained from GitHub.

Before installation, `dnf repolist --enabled` returned no repository. Temporary
blackhole routes blocked external IPv4 and IPv6 egress while preserving the
directly connected management subnet; an HTTPS probe to an upstream repository
failed as required.

```bash
sudo /opt/Zabbix/install.sh
sudo /opt/Zabbix/verify.sh
cat /proc/sys/kernel/random/boot_id
sudo systemctl reboot
sudo /opt/Zabbix/verify.sh
```

Useful output: the installer returned `ok=162 changed=54 failed=0` and
`PASS: installation completed`. The standalone verifier passed 31 tasks before
reboot and again after reboot. A separately recorded reboot changed boot ID
from `1675ac4d-4aac-4d1b-9cfe-420751d57e8d` to
`d83b11d9-26a4-4c0a-b049-6ca2e887fd34`.

Installed versions were Zabbix server/agent/web `7.0.30-release1.el9`,
PostgreSQL `16.10`, nginx `1.24.0`, and PHP-FPM `8.3.19`. Enabled module streams
from local metadata were PostgreSQL 16, PHP 8.3, and nginx 1.24. PostgreSQL,
Zabbix Server, nginx, PHP-FPM, Agent 2, and firewalld were all enabled and
active. The frontend returned `Zabbix`; SELinux remained `Enforcing`.
The installed repository had `baseurl=file://...`, `gpgcheck=1`, and the
local-only repo ID `zabbix-offline`; verifier-controlled DNF disabled every
other repository.

The post-reboot database guard passed with only the stock normal host and
`Admin,guest`; tokens, discovered hosts, and discovered services were zero.
Huawei and FortiGate template counts were each one, and Huawei
`net.if.discovery` count was one. The runtime repository scan examined 122
files and returned every policy result PASS, including exact deployment-secret
absence.

### 4.6 Live SNMP polling — UNTESTED (non-blocking)

Huawei and FortiGate official template presence and Huawei interface LLD are
PASS. Live Huawei and FortiGate polling remain UNTESTED because no explicitly
approved real SNMP endpoint exists. The known mock addresses are intentionally
non-routable and were not used. This does not block core platform release.

## 5. Release gate — PASS

All critical platform gates passed on the disposable RHEL 9.6 guest: connected
clean install, unchanged rerun, clean database, destructive safety, reboot,
standalone verification, PostgreSQL 16, Zabbix 7.0.30, frontend, Admin policy,
SELinux/AVC, firewalld, official Huawei/FortiGate structures, repository and
payload policy, exact runtime-password absence, and airgapped installation.
Only live vendor polling remains UNTESTED and non-blocking.
