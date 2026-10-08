"""Regenerates reporting/daily-reporting/lib/zrs/data/selftest.json (synthetic, no real hosts)."""
import json
from common import APP, dataset, make_cfg, WAN_LINKS

cfg = make_cfg(wan={"links": WAN_LINKS})
ds, cfg, _ = dataset("daily_network_health", cfg=cfg)
cfg = json.loads(json.dumps(cfg))
for k in ("zabbix",):
    cfg[k]["api_url"] = "https://selftest.invalid/api_jsonrpc.php"
ds["audit"]["source_api"] = "https://selftest.invalid"
(APP / "lib" / "zrs" / "data").mkdir(exist_ok=True)
(APP / "lib" / "zrs" / "data" / "selftest.json").write_text(json.dumps({"cfg": cfg, "dataset": ds}, indent=1, sort_keys=True))
print("written", ds["dataset_sha256"][:12])
