# M1 fping source amendment

The original M1 run stopped because the approved BaseOS, AppStream, and official
Zabbix 7.0 sources did not provide `fping`. The owner then authorized only:

`https://repo.zabbix.com/non-supported/rhel/9/x86_64/`

for the `fping` runtime dependency.

Independent verification observed:

- repository metadata HTTP 200 and repomd SHA256
  `1d97b215e1281c216faddd2bfdb85a61ea918aa1f8868ec9cf7c4908ad46493c`;
- repository content `fping-0:5.1-1.el9.x86_64`;
- RPM SHA256
  `973ea94723ef69a9196c9f72f44ca414b7857a75ccc02e8a6492293fb010073c`;
- official key fingerprint
  `D9AA 84C2 B617 479C 6E4F CF4D 19F2 4753 08EF A7DD`;
- trusted RPM header and payload signature status `OK` using that key.

The first temporary RPM database attempt used an unsuitable flat path and
failed before import. The retained second attempt used the already validated
nested `/var/lib/rpm` layout and passed. Both raw transcripts are retained.

The source is explicitly classified as Zabbix **non-supported**. M1 constrains
it with `includepkgs=fping` and independently rejects any generated lock entry
from that repository unless it is the exact pinned `fping` NEVRA and SHA256.
EPEL and source compilation remain prohibited.

Official references consulted:

- `https://www.zabbix.com/documentation/7.0/en/manual/installation/install_from_packages`
- `https://repo.zabbix.com/non-supported/rhel/9/x86_64/`
- `https://repo.zabbix.com/RPM-GPG-KEY-ZABBIX-08EFA7DD`
