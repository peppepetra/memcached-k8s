# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import MagicMock, patch

from charm import MemcachedK8SCharm
from ops.model import ActiveStatus, MaintenanceStatus
from ops.pebble import ConnectionError
from ops.testing import Harness


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        """Setup the harness object."""
        self.harness = Harness(MemcachedK8SCharm)
        self.harness.begin()
        self.harness.add_oci_resource("memcached-image")

    def tearDown(self) -> None:
        """Cleanup the harness."""
        self.harness.cleanup()

    #
    # Hooks
    #
    def test__on_config_changed(self):
        self.assertEqual(self.harness.charm._stored.tcp_port, 11211)
        self.harness.update_config({"tcp-port": 11111})
        self.assertEqual(self.harness.charm._stored.tcp_port, 11111)

    def test__on_config_changed_pebble_api_connection_error_1(self) -> None:
        self.harness.charm.unit.get_container = MagicMock()
        self.harness.charm.unit.get_container.return_value.get_plan = MagicMock(
            side_effect=ConnectionError("connection timeout")
        )
        with self.assertLogs(level="DEBUG") as logger:
            self.harness.update_config({"tcp-port": 11111})
            self.assertIn(
                "DEBUG:charm:The Pebble API is not ready yet. Error message: connection timeout",
                logger.output,
            )
            self.assertNotIn(
                "DEBUG:charm:Pebble plan has already been loaded. No need to update the config.",
                logger.output,
            )

    def test__on_config_changed_pebble_api_connection_error_2(self) -> None:
        self.harness.charm.unit.get_container = MagicMock()
        self.harness.charm.unit.get_container.return_value.get_plan.return_value.to_dict = (
            MagicMock(return_value={})
        )
        self.harness.charm.unit.get_container.return_value.add_layer = MagicMock(
            side_effect=ConnectionError("connection timeout")
        )
        with self.assertLogs(level="DEBUG") as logger:
            self.harness.update_config({"tcp-port": 11111})
            self.assertIn(
                "DEBUG:charm:The Pebble API is not ready yet. Error message: connection timeout",
                logger.output,
            )
            self.assertNotIn(
                "DEBUG:charm:Pebble plan has already been loaded. No need to update the config.",
                logger.output,
            )

    def test__on_config_changed_same_plan(self) -> None:
        self.harness.charm.unit.get_container = MagicMock()
        self.harness.charm.unit.get_container.return_value.get_plan.return_value.to_dict = (
            MagicMock(return_value=self.harness.charm._memcached_layer())
        )
        with self.assertLogs(level="DEBUG") as logger:
            self.harness.update_config({"tcp-port": 11211})
            self.assertIn(
                "DEBUG:charm:Pebble plan has already been loaded. No need to update the config.",
                logger.output,
            )
            self.assertNotIn(
                "DEBUG:charm:The Pebble API is not ready yet. Error message: connection timeout",
                logger.output,
            )

    def test__on_config_changed_wrong_tcp_port(self) -> None:
        self.harness.update_config({"tcp-port": -10})
        self.assertEqual(self.harness.charm._stored.tcp_port, 11211)
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-p 11211", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    def test__on_config_changed_valid_udp_port(self) -> None:
        self.harness.update_config({"udp-port": 11111})
        self.assertEqual(self.harness.charm._stored.udp_port, 11111)
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-U 11111", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    def test__on_config_changed_wrong_mem_size(self) -> None:
        self.harness.update_config({"size": 10})
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-m 64", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    def test__on_config_changed_wrong_connection_limit(self) -> None:
        self.harness.update_config({"connection-limit": 0})
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-c 1024", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    def test__on_config_changed_wrong_request_limit(self) -> None:
        self.harness.update_config({"request-limit": 0})
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-R 20", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    def test__on_config_changed_wrong_num_threads(self) -> None:
        self.harness.update_config({"threads": 0})
        plan = self.harness.get_container_pebble_plan("memcached")
        self.assertIn("-t 4", plan.to_yaml())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus("Pod is ready"))

    @patch("subprocess.check_output")
    def test__on_config_changed_with_rel_memcached_joined(self, check_output: MagicMock) -> None:
        check_output.return_value = b"10.0.0.1"
        expected_relation_data = {
            "host": "10.0.0.1",
            "port": "11111",
            "udp-port": "0",
        }
        relation_id = self.harness.add_relation('memcache', 'memcached-k8s-client-test')
        self.harness.add_relation_unit(relation_id, "memcached-k8s-client-test/0")
        self.harness.update_config({"tcp-port": 11111})
        self.assertEqual(
            expected_relation_data,
            self.harness.model.get_relation("memcache").data[self.harness.charm.unit]
        )
        check_output.assert_called()

    def test__is_not_running(self) -> None:
        container = self.harness.charm.unit.get_container("memcached")
        service_not_running = self.harness.charm._is_running(container, "memcached")
        self.assertFalse(service_not_running)
        self.assertEqual(self.harness.model.unit.status, MaintenanceStatus(""))

    def test__on_restart_action(self):
        self.harness.charm.unit.get_container = MagicMock()
        action_event = MagicMock()
        self.harness.charm._on_restart_action(action_event)

        action_event.set_results.assert_called()

    @patch("pymemcache.client.base.Client.stats")
    def test__on_get_stats_action(self, client_stats: MagicMock):
        action_event = MagicMock(params={"settings": False})
        self.harness.charm._stored.ssl_enabled = False
        self.harness.charm._on_get_stats_action(action_event)

        action_event.set_results.assert_called()
        client_stats.assert_called()

    @patch("pymemcache.client.base.Client.stats")
    def test__on_get_stats_action_with_settings(self, client_stats: MagicMock):
        action_event = MagicMock(params={"settings": True})
        self.harness.charm._stored.ssl_enabled = False
        self.harness.charm._on_get_stats_action(action_event)

        action_event.set_results.assert_called()
        client_stats.assert_called_with("settings")
