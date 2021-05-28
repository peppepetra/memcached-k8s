#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk
import base64
import logging
import os
import pprint
import ssl
import subprocess

from ops.charm import CharmBase, HookEvent, RelationEvent, ActionEvent
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, Container, ModelError
from ops.pebble import APIError, ConnectionError, Layer, ServiceStatus

from pymemcache.client.base import Client

logger = logging.getLogger(__name__)

WORKLOAD_CONTAINER = "memcached"
DEFAULT_TCP_PORT = 11211
DEFAULT_MEMORY_SIZE = 64
DEFAULT_THREADS = 4
DEFAULT_REQUEST_LIMIT = 20
DEFAULT_CONNECTION_LIMIT = 1024
SSL_CERT_PATH = "/cert.pem"
SSL_KEY_PATH = "/ssl_key.key"
SSL_CA_CERT_PATH = "/cacert.pem"


class MemcachedK8SCharm(CharmBase):
    """Charm to run Memcached on Kubernetes"""
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        # Hooks
        self.framework.observe(self.on.memcached_pebble_ready, self._on_config_changed)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

        # Actions
        self.framework.observe(self.on.restart_action, self._on_restart_action)
        self.framework.observe(self.on.get_stats_action, self._on_get_stats_action)

        # Relations
        self.framework.observe(
            self.on["memcache"].relation_joined, self._on_memcache_relation_joined
        )

        # Set defaults for variable stored in the StoredState
        self._stored.set_default(tcp_port=DEFAULT_TCP_PORT, udp_port=0, ssl_enable=False)

    #
    # Hooks
    #
    def _on_config_changed(self, event: HookEvent) -> None:
        """Handle the pebble_ready and config_changed event for the memcached container."""

        container = self.unit.get_container(WORKLOAD_CONTAINER)
        try:
            plan = container.get_plan().to_dict()
        except (APIError, ConnectionError) as error:
            logger.debug(f"The Pebble API is not ready yet. Error message: {error}")
            event.defer()
            return

        # Push certificates if available
        self._push_certificates(container)
        # Write the ca_cert to the charm the
        self._render_ca_cert_to_charm_container()

        logger.debug(f"[*] container plan => {plan}")
        pebble_config = Layer(raw=self._memcached_layer())
        # If there's no new config, do nothing
        if plan.get("services", {}) == pebble_config.to_dict()["services"]:
            logger.debug("Pebble plan has already been loaded. No need to update the config.")
            return

        try:
            # Add config layer
            container.add_layer("memcached", pebble_config, combine=True)
        except (APIError, ConnectionError) as error:
            logger.debug(f"The Pebble API is not ready yet. Error message: {error}")
            event.defer()
            return

        # If the service is INACTIVE, then skip this step
        if self._is_running(container, WORKLOAD_CONTAINER):  # pragma: no cover
            container.stop(WORKLOAD_CONTAINER)
        container.start(WORKLOAD_CONTAINER)

        # Update cache relation data if available.
        for relation in self.model.relations['memcache']:
            relation.data[self.unit]["host"] = subprocess.check_output(
                ["unit-get", "private-address"]).decode().strip()
            relation.data[self.unit]["port"] = str(self._stored.tcp_port)
            relation.data[self.unit]["udp-port"] = str(self._stored.udp_port)

        self.unit.status = ActiveStatus("Pod is ready")

    #
    # Actions
    #
    def _on_restart_action(self, event: ActionEvent) -> None:
        """Handle the restart action"""
        container = self.unit.get_container(WORKLOAD_CONTAINER)
        # If the service is INACTIVE, then skip this step
        if self._is_running(container, WORKLOAD_CONTAINER):  # pragma: no cover
            container.stop(WORKLOAD_CONTAINER)
        container.start(WORKLOAD_CONTAINER)

        event.set_results({"restart": "Memcached is restarted"})

    def _on_get_stats_action(self, event: ActionEvent) -> None:
        """Handle the get-stats action"""
        tls_context = None
        if self._stored.ssl_enabled:
            tls_context = ssl.create_default_context(
                cafile=SSL_CA_CERT_PATH,
            )
            # This is needed as client contact memcached always on localhost
            tls_context.check_hostname = False

        client = Client("localhost:{}".format(self._stored.tcp_port), tls_context=tls_context)
        settings = event.params["settings"]

        if settings:
            stats = client.stats("settings")
        else:
            stats = client.stats()

        # Decode byte string keys of dict result and pretty print it
        pp = pprint.PrettyPrinter()
        result = pp.pformat(dict([(k.decode("utf-8"), v) for k, v in stats.items()]))
        event.set_results({"get-stats": result})

    #
    # Relations
    #
    def _on_memcache_relation_joined(self, event: RelationEvent) -> None:
        """Provide to the client the memcached endpoint."""
        relation_data = {
            "host": subprocess.check_output(["unit-get", "private-address"]).decode().strip(),
            "port": str(self._stored.tcp_port),
            "udp-port": str(self._stored.udp_port),
        }
        event.relation.data[self.unit].update(relation_data)

    #
    # Helpers
    #
    def _memcached_layer(self) -> dict:
        """Returns Pebble configuration layer for Memcached."""
        cmd = []

        cmd.append("memcached")
        cmd.append("-u root")

        # Configure TCP port
        tcp_port = self.config["tcp-port"]
        if tcp_port < 1023 or tcp_port > 49151:
            logger.debug(f"Wrong tcp-port provided: {tcp_port}. Using default {DEFAULT_TCP_PORT}")
            tcp_port = DEFAULT_TCP_PORT

        self._stored.tcp_port = tcp_port
        cmd.append(f"-p {tcp_port}")
        logger.info(f"Listening on TCP port {tcp_port}")

        # Configure UDP port
        udp_port = self.config["udp-port"]
        if udp_port > 0 and 1023 < udp_port < 49151:
            self._stored.udp_port = udp_port
            logger.info(f"Using UDP port {udp_port}")
            cmd.append(f"-U {udp_port}")
        else:
            logger.debug("Not using UDP port")

        # Configuring memory size
        mem_size = self.config["size"]
        if mem_size < 64:
            logger.debug(
                f"Memory size provided lower than 64. Using default {DEFAULT_MEMORY_SIZE} MB")
            mem_size = DEFAULT_MEMORY_SIZE

        cmd.append(f"-m {mem_size}")
        logger.info(f"Memory size set to {mem_size} MB")

        # Configuring connection limit
        connection_limit = self.config["connection-limit"]
        if connection_limit < 1:
            logger.debug(
                f"Provided negative connection limit {connection_limit}. "
                f"Using default {DEFAULT_CONNECTION_LIMIT}")
            connection_limit = DEFAULT_CONNECTION_LIMIT

        cmd.append(f"-c {connection_limit}")
        logger.info(f"Connection limit set to {connection_limit}")

        # Configuring request limit
        request_limit = self.config["request-limit"]
        if request_limit < 1:
            logger.debug(
                f"Provided negative request limit {request_limit}. "
                f"Using default {DEFAULT_REQUEST_LIMIT}")
            request_limit = DEFAULT_REQUEST_LIMIT

        cmd.append(f"-R {request_limit}")
        logger.info(f"Request limit set to {request_limit}")

        # Configuring threads
        threads = self.config["threads"]
        if threads < 1:
            logger.debug(
                f"Provided negative number threads {threads}. Using default {DEFAULT_THREADS}")
            threads = DEFAULT_THREADS

        cmd.append(f"-t {threads}")
        logger.info(f"Threads set to {threads}")

        if self.config.get("ssl-cert"):
            cmd.append("--enable-ssl")
            cmd.append(f"-o ssl_chain_cert={SSL_CERT_PATH}")
            self._stored.ssl_enabled = True

        if self.config.get("ssl-key"):
            cmd.append(f"-o ssl_key={SSL_KEY_PATH}")

        if self.config.get("ssl-ca"):
            cmd.append(f"-o ssl_ca_cert={SSL_CA_CERT_PATH}")

        pebble_layer = {
            "summary": "memcached layer",
            "description": "pebble config layer for memcached",
            "services": {
                "memcached": {
                    "override": "replace",
                    "summary": "memcached",
                    "command": " ".join(cmd),
                    "startup": "enabled",
                }
            },
        }
        return pebble_layer

    def _is_running(self, container: Container, service: str) -> bool:
        """Helper method to determine if a given service is running in a given container"""
        try:
            svc = container.get_service(service)
            return svc.current == ServiceStatus.ACTIVE
        except ModelError:
            return False

    def _push_certificates(self, container: Container) -> None:
        """Push certificates to the workload container"""
        if self.config.get("ssl-cert"):
            certificate = base64.b64decode(self.config["ssl-cert"])
            container.push(SSL_CERT_PATH, certificate, permissions=0o600)
            logger.info(f"Pushed SSL certificate to memcached at {SSL_CERT_PATH}")
        if self.config.get("ssl-key"):
            cert_key = base64.b64decode(self.config["ssl-key"])
            container.push(SSL_KEY_PATH, cert_key, permissions=0o600)
            logger.info(f"Pushed SSL key to memcached at {SSL_KEY_PATH}")
        if self.config.get("ssl-ca"):
            ca_cert = base64.b64decode(self.config["ssl-ca"])
            container.push(SSL_CA_CERT_PATH, ca_cert, permissions=0o600)
            logger.info(f"Pushed SSL CA cert to memcached at {SSL_CA_CERT_PATH}")

    def _render_ca_cert_to_charm_container(self) -> None:
        """Render CA cert to the charm container for the get-stats action."""
        if self.config.get("ssl-ca"):
            with open(SSL_CA_CERT_PATH, "w+") as fh:
                ca_cert = base64.b64decode(self.config["ssl-ca"])
                fh.write(ca_cert.decode("utf-8"))
            os.chmod(SSL_CA_CERT_PATH, 0o600)


if __name__ == "__main__":  # pragma: no cover
    main(MemcachedK8SCharm)
