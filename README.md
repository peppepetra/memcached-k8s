# memcached-k8s

## Overview

This charm installs [Memcached](http://memcached.org) on Kubernetes. It uses the [Python Operator Framework](https://github.com/canonical/operator) ([API docs](https://ops.readthedocs.io/en/latest/)) and K8s sidecar container with [Pebble](https://github.com/canonical/pebble).

## Description

[Memcached](http://memcached.org) is a Free & open source, high-performance, distributed memory object caching system, generic in nature, but intended for use in speeding up dynamic web applications by alleviating database load.

Memcached is an in-memory key-value store for small chunks of arbitrary data (strings, objects) from results of database calls, API calls, or page rendering.

## Usage

You can deploy a memcached instance with

    juju deploy memcached-k8s

The charm provides two actions:

1. `restart`: restart and flush content of a memcached unit

```
    juju run-action --wait memcached-k8s/0 restart 
```
2. `get-stats`: returns memcached stats. It accepts a boolean argument `settings` (default `false`) to get the memcached settings (ref. [Memcached cheat sheet](https://lzone.de/cheat-sheet/memcached))

```
    juju run-action --wait memcached-k8s/0 get-stats                 # equivalent memcached command "stats"
    juju run-action --wait memcached-k8s/0 get-stats settings=true   # equivalent memcached command "stats settings"
```

## Roadmap

* Add hugepages support. Blocked by [LP#1919976](https://bugs.launchpad.net/juju/+bug/1919976)
* Add functional tests

## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests

To test the deploy of the charm locally, use [MicroK8s](https://microk8s.io/)

```
# Install/Setup MicroK8s

$ sudo snap install --classic microk8s
$ sudo usermod -aG microk8s $(whoami)
$ sudo microk8s status --wait-ready
$ sudo microk8s enable storage dns ingress
$ sudo snap alias microk8s.kubectl kubectl
$ newgrp microk8s

# Install Charmcraft
$ sudo snap install charmcraft

# Install Juju 2.9+
$ sudo snap install juju --classic 

# Bootstrap MicroK8s
$ juju bootstrap microk8s micro
$ juju add-model development

# Build the charm and deploy
$ git clone https://github.com/peppepetra/memcached-k8s
$ cd memcached-k8s 
$ charmcraft pack
$ juju deploy ./memcached-k8s.charm --resource memcached-image=memcached:latest 
```