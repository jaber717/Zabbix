import unittest

from netalert import config, handover
from netalert.zbx import ZabbixClient
from tests.fake_zabbix import MockZabbix


def client():
    z = MockZabbix()
    z.add_host("RTR-01", ["Gi0/0", "Gi0/1"])
    return ZabbixClient(z.transport(), read_only=True)


class Handover(unittest.TestCase):
    def test_flat_records_are_normalized(self):
        d = handover.normalize([{"device": "RTR-01", "ifname": "Gi0/0", "peer": "to RTR-02", "site": "HQ",
                                 "severity": "disaster"}])
        self.assertEqual(d["hosts"]["RTR-01"]["interfaces"]["Gi0/0"]["description"], "to RTR-02")
        self.assertEqual(config.parse(d).problems, [])

    def test_record_without_interface_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            handover.normalize([{"host": "RTR-01"}])

    def test_unknown_shape_is_rejected(self):
        with self.assertRaises(config.ConfigError):
            handover.normalize({"something": 1})

    def test_only_verified_entries_reach_the_policy(self):
        data = handover.normalize({"hosts": {
            "RTR-01": {"site": "HQ", "interfaces": {"Gi0/0": {"description": "ok"},
                                                    "Gi0/9": {"description": "typo"}}},
            "GHOST": {"interfaces": {"Gi0/0": {"description": "no such host"}}}}})
        verified, review, _ = handover.verify(client(), data)
        self.assertEqual(list(verified["hosts"]), ["RTR-01"])
        self.assertEqual(list(verified["hosts"]["RTR-01"]["interfaces"]), ["Gi0/0"])
        flagged = dict(((h, i), why) for h, i, why in review)
        self.assertIn("not found", flagged[("RTR-01", "Gi0/9")])
        self.assertIn("not found in Zabbix", flagged[("GHOST", "Gi0/0")])
        self.assertIn("REVIEW REQUIRED", handover.render_review(review))
        self.assertIn("Gi0/9", handover.render_review(review))

    def test_generated_policy_is_a_valid_policy(self):
        data = handover.normalize({"hosts": {"RTR-01": {"interfaces": {"Gi0/0": {"description": "ok"}}}}})
        verified, review, _ = handover.verify(client(), data)
        import yaml
        text = handover.render_policy(verified, "# x\n")
        self.assertEqual(config.parse(yaml.safe_load(text)).problems, [])
        self.assertEqual(review, [])


if __name__ == "__main__":
    unittest.main()
