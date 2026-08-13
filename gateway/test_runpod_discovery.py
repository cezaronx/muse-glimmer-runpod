import unittest
from unittest.mock import patch

from runpod_discovery import RunpodPodDiscovery


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.discovery = RunpodPodDiscovery(
            api_key="test",
            template_id="template-1",
            data_center_id="EU-RO-1",
            network_volume_id="volume-1",
        )

    def pod(self, **overrides):
        item = {
            "id": "pod-new-id",
            "name": "muse-glimmer-pod-ro1-abc",
            "desiredStatus": "RUNNING",
            "endpointId": None,
            "templateId": "template-1",
            "dataCenterId": "EU-RO-1",
            "networkVolume": {"id": "volume-1"},
            "publicIp": "203.0.113.10",
            "portMappings": {"8000": 19000, "22": 19022},
            "gpu": {"id": "NVIDIA RTX PRO 4500 Blackwell"},
        }
        item.update(overrides)
        return item

    @patch.object(RunpodPodDiscovery, "_list_pods")
    def test_resolves_current_id_and_port(self, list_pods):
        list_pods.return_value = [self.pod()]
        connection = self.discovery.discover()
        self.assertEqual(connection.pod_id, "pod-new-id")
        self.assertEqual(connection.base_url, "http://203.0.113.10:19000")
        self.assertEqual(connection.ssh_public_port, 19022)

    @patch.object(RunpodPodDiscovery, "_list_pods")
    def test_ignores_stopped_or_wrong_pods(self, list_pods):
        list_pods.return_value = [
            self.pod(desiredStatus="EXITED"),
            self.pod(id="wrong", templateId="other"),
        ]
        self.assertIsNone(self.discovery.discover())

    @patch.object(RunpodPodDiscovery, "_list_pods")
    def test_rejects_ambiguous_running_pods(self, list_pods):
        list_pods.return_value = [self.pod(), self.pod(id="pod-2")]
        with self.assertRaisesRegex(RuntimeError, "More than one"):
            self.discovery.discover()


if __name__ == "__main__":
    unittest.main()
