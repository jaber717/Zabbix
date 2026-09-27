from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[2]
module = root / "frontend/modules/NetworkUtilization"
manifest = json.loads((module / "manifest.json").read_text())
assert manifest["id"] == "netops_network_utilization"
assert manifest["version"] == (module / "VERSION").read_text().strip()
required = [
    "Widget.php", "actions/WidgetView.php", "actions/ConfigUpdate.php",
    "assets/css/network-utilization.css", "assets/js/class.widget.js",
    "collector/ZabbixLinkUtilizationCollector.php", "config/LinkDefinitionRepository.php",
    "domain/LinkUtilizationResolver.php", "views/widget.view.php"
]
for name in required:
    assert (module / name).is_file(), name
all_text = "\n".join(path.read_text(errors="replace") for path in module.rglob("*") if path.is_file())
assert "localStorage" not in all_text
assert "ifindex" not in (module / "config/link-definitions.json").read_text().lower()
assert "ifIndex" not in (module / "config/LinkDefinitionRepository.php").read_text()
collector = (module / "collector/ZabbixLinkUtilizationCollector.php").read_text()
assert "if($units==='Bps')$factor=8.0" in collector
assert "if($mode!=='rate')return null" in collector
assert "API::History()->get" in collector and "time_from" in collector
assert "API::Trend()->get" in collector
resolver = (module / "domain/LinkUtilizationResolver.php").read_text()
assert "max($in_util, $out_util)" not in resolver  # nullable helper is deliberate
assert "resetSafeDelta" in resolver and "MIN_PERCENTILE_SAMPLES" in resolver
assert not re.search(r"(?i)(password|token|secret)\s*[:=]\s*['\"][^'\"]+", all_text)
availability = root / "frontend/modules/NetworkAvailability"
assert availability.is_dir()
install = (root / "scripts/install-network-utilization.sh").read_text()
verify = (root / "scripts/verify-network-utilization.sh").read_text()
rollback = (root / "scripts/rollback-network-utilization.sh").read_text()
assert "RUNTIME_CONFIGURATION=PRESERVED" in install
assert "SERVICE_RESTARTS=NONE" in install
assert "link-definitions.json" in verify
assert "RUNTIME_CONFIGURATION=PRESERVED" in rollback
assert "systemctl restart" not in install + verify + rollback
print("PASS: static module, data-path, bounded-history, identity and secret contracts")
