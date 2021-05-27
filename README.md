# memcached-k8s

## Description

[Memcached](http://memcached.org) is a Free & open source, high-performance, distributed memory object caching system, generic in nature, but intended for use in speeding up dynamic web applications by alleviating database load.

Memcached is an in-memory key-value store for small chunks of arbitrary data (strings, objects) from results of database calls, API calls, or page rendering.

## Usage

You can deploy a memcached instance with

    juju deploy memcached-k8s

The charm provides two actions:

1. `restart`: restart and flush content of a memcached unit


    juju run-action --wait memcached-k8s/0 restart 

2. `get-stats`: returns memcached stats. It accepts a boolean argument `settings` (default `false`) to get the memcached settings (ref. [Memcached cheat sheet](https://lzone.de/cheat-sheet/memcached))


    juju run-action --wait memcached-k8s/0 get-stats                 # equivalent memcached command "stats"
    juju run-action --wait memcached-k8s/0 get-stats settings=true   # equivalent memcached command "stats settings"


## Developing

Create and activate a virtualenv with the development requirements:

    virtualenv -p python3 venv
    source venv/bin/activate
    pip install -r requirements-dev.txt

## Testing

The Python operator framework includes a very nice harness for testing
operator behaviour without full deployment. Just `run_tests`:

    ./run_tests
