# Milestone 0 Capability Check

Observed 2026-09-01 from the Codex execution environment. A stated lab component
is not treated as access. Evidence paths are relative to the repository root.

| Resource | State | Verification |
|---|---|---|
| Local shell | AVAILABLE | PowerShell executed local identity/tool probes; see `raw/local-capability.txt`. |
| Current filesystem | AVAILABLE | Workspace was listed and this repository was created under the accessible workspace. |
| Git repository | AVAILABLE | No repository existed at the workspace or target initially; Milestone 0 initialized the new target repository and verified it later in this run. |
| Internet | AVAILABLE | Header-only HTTPS requests to official Zabbix and Red Hat sites returned HTTP 200; see `raw/internet-capability.txt`. This verifies connectivity only, not package/version availability. |
| RHEL build VM | AVAILABLE | TCP/22 opened after power-on and public-key SSH authenticated as the unprivileged `jaber` account to `192.168.1.91` (`netbox-dev`). Passwordless sudo was proven once with `sudo -n true` and then used only for authorized read-only subscription-manager queries. See `raw/rhel-build-baseline.txt` and `raw/rhel-build-repository-readiness.txt`. |
| Proxmox API/SSH | AVAILABLE | Existing key authenticated in batch mode to `192.168.1.100`; `hostname`, `pveversion`, `pvesh`, `qm list`, and `pct list` reads succeeded; see `raw/proxmox-read-only.txt`. |
| NetBox LXC/API | AVAILABLE / LIMITED | LXC 9000 was read through Proxmox; local and remote GETs succeeded. M4 identified NetBox 4.6.9/API 4.6 (Django 6.0.8) and reconfirmed HTTP 403 for VM, VM-interface, tag, and custom-field endpoints. See `raw/netbox-read-only.txt` and `evidence/m4/PREFLIGHT.md`. |
| PNET/EVE | UNAVAILABLE | Proxmox inventory shows QEMU 110 and 120 stopped. They were not started and no guest access was attempted. |
| Portal source repository | AVAILABLE | A local source tree exists at `../netbox-topology`; selected filenames and routes were inspected read-only. It is a source directory, not an independently detected Git repository; see `raw/portal-source-inventory.txt`. |

M0.5 subsequently enabled and verified standard RHEL 9 BaseOS/AppStream and used
them with the temporary official Zabbix 7.0 source in a clean installroot. Source
readiness for M1 is AVAILABLE; see `evidence/m0.5/`.

No credential value or private-key content was read into evidence. Subscription
identity and organization identifiers were redacted from raw output.
