# Required Network Flows

The installer creates source-restricted firewalld rich rules. It does not add a
global service or open a port to all sources. Environment owners must replace
the CIDR variables with approved management and monitoring networks.

| Destination on Zabbix VM | TCP port | Source variable | Purpose |
|---|---:|---|---|
| nginx | 443 | `zabbix_firewall_web_sources` | HTTPS frontend/API when TLS is enabled |
| nginx | 80 | `zabbix_firewall_web_sources` | Optional HTTP-to-HTTPS redirect, or HTTP when TLS is disabled |
| Zabbix Server | 10051 | `zabbix_firewall_server_sources` | Active agents, proxies, and approved senders |
| Agent 2 | 10050 | `zabbix_firewall_agent_sources` | Approved server/proxy passive checks |

Local PostgreSQL listens only on loopback by default and therefore has no
firewalld exposure. External database mode requires an independently approved
outbound TCP flow from Zabbix Server/PHP to `zabbix_db_host:zabbix_db_port`
(normally 5432); the M2 firewall role does not create remote firewall rules.

Package installation and verification require no Internet egress. DNF is
explicitly restricted to the local `file://` repository.

## M3 home-lab observation

The dual-purpose M3 host preserves pre-existing NetBox nginx listeners and
firewall ports 80/443. Zabbix uses HTTPS 8443 instead of 443. Firewalld has
source-restricted rich rules for `192.168.1.0/24` to TCP 8443, 10050, and 10051;
the installer did not add any global Zabbix service/port. PostgreSQL remains on
`127.0.0.1:5432`. Every converge package transaction disabled all repositories
except the accepted local `zabbix-offline` repository; no package egress was
used.
