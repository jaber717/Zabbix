from pathlib import Path
import json,re,sys
root=Path(__file__).resolve().parents[2]
module=root/'frontend/modules/DeviceHealth'
required=['manifest.json','Widget.php','VERSION','actions/WidgetView.php','collector/ZabbixDeviceHealthCollector.php','domain/DeviceHealthResolver.php','domain/MetricFreshnessPolicy.php','domain/IssueNormalizer.php','views/widget.view.php','assets/css/device-health.css','assets/js/class.widget.js']
for rel in required:
    assert (module/rel).is_file(), rel
manifest=json.loads((module/'manifest.json').read_text())
assert manifest['version']==(module/'VERSION').read_text().strip()=='1.0.0'
collector=(module/'collector/ZabbixDeviceHealthCollector.php').read_text()
assert collector.count('API::')==4, 'core collector must retain four bulk API calls'
assert 'API::History' not in collector and 'API::Trend' not in collector
resolver=(module/'domain/DeviceHealthResolver.php').read_text()
assert 'issueCategory' in resolver and 'normalizedIssues' in resolver
css=(module/'assets/css/device-health.css').read_text()
assert 'container-type:inline-size' in css and css.count('@container')>=3
for untouched in ['frontend/modules/NetworkAvailability','frontend/modules/NetworkUtilization']:
    pass
for path in module.rglob('*'):
    if path.is_file():
        text=path.read_text(errors='ignore')
        assert not re.search(r'(?i)(password|token|secret)\s*[:=]\s*["\'][^"\']+["\']',text),path
print('STATIC=PASS')
