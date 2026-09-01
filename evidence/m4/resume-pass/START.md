# M4 Permission-Pass Resumption Start

Date: 2026-09-02

- Branch: `main`
- Starting commit: `a512465a33415aee60d9e879f509e786f45123bb`
- Prior M4 state: blocked after the installed credential still received four
  HTTP 403 responses.
- Operator-reported action: grant the named `topology-portal` principal only
  `view` access to virtual machines, VM interfaces, tags, and custom fields,
  with empty constraints.
- Authorized continuation: revalidate with the existing credential and resume
  the existing M4 gates only if all four reads pass.

No NetBox write, change-budget override, destructive Zabbix operation, M5, M6,
or external push is authorized by this resumption.
