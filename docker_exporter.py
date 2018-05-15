#! /usr/bin/env python3

from concurrent.futures._base import TimeoutError
import asyncio
import itertools
import os
import time

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectorError
from aiostream import stream
from prometheus_client import generate_latest, CollectorRegistry, Gauge
from prometheus_client.parser import text_string_to_metric_families
import aiodocker
import aiohttp


async def fetch_container_metrics(container):
    attrs = await container.show()

    monitoring_port = attrs.get('Config', {}).get('Labels', {}).get('io.unrouted.docker-exporter.port', None)
    if not monitoring_port:
        return

    network = attrs['HostConfig']['NetworkMode']

    monitoring_address = None

    if os.environ.get('DOCKER_EXPORTER_NETWORK_MODE', 'container') == 'container':
        monitoring_address = attrs['NetworkSettings']['Networks'][network]['IPAddress']
    else:
        if network == 'host':
            monitoring_address = '127.0.0.1'
        elif nat_port:
            nat_port = attrs['NetworkSettings']['Ports'].get(f'{monitoring_port}/tcp', None)
            monitoring_port = nat_port[0]['HostPort']
            monitoring_address = nat_port[0]['HostIp']
            if monitoring_address == '0.0.0.0':
                monitoring_address = '127.0.0.1'

    registry = CollectorRegistry()
    up = Gauge('up', 'Is this resource up?', ['container'], registry=registry).labels(attrs['Name'])
    up.set(0)

    latency = Gauge('latency', 'How long is it taking to probe these metrics', ['container'], registry=registry).labels(attrs['Name'])
    latency.set(0)

    before = time.time()

    metrics_text = None

    if monitoring_address:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f'http://{monitoring_address}:{monitoring_port}/metrics', timeout=5) as response:
                    metrics_text = await response.text()
            except TimeoutError:
                print(f'http://{monitoring_address}:{monitoring_port}/metrics: Timeout')

    if metrics_text:
        try:
            for metric in text_string_to_metric_families(metrics_text):
                yield metric
            up.set(1)
        except Exception:
            print(f'http://{monitoring_address}:{monitoring_port}/metrics: Error parsing')

    latency.set(time.time() - before)

    for metric in registry.collect():
        yield metric


async def fetch_metrics(request):
    docker = aiodocker.Docker()
    try:
        containers = await docker.containers.list()

        metrics = await stream.list(stream.merge(*[fetch_container_metrics(c) for c in containers]))

        class RestrictedRegistry(object):
            def collect(self):
                return metrics

        print(generate_latest(RestrictedRegistry()))

        return web.Response(
            body=generate_latest(RestrictedRegistry()),
            content_type='text/plain; version=0.4',
            charset='utf-8',
        )

    finally:
        await docker.close()


if __name__ == '__main__':
    app = web.Application()
    app.add_routes([web.get('/metrics', fetch_metrics)])
    web.run_app(
        app,
        port=int(os.environ.get('DOCKER_EXPORTER_PORT', '8080')),
    )
