import argparse
import asyncio
import itertools
import json
from ipaddress import IPv4Network, IPv4Address
from os import path
from threading import Thread, Lock
from typing import Iterable, Iterator, Callable

from mcstatus import JavaServer
from mcstatus.pinger import PingResponse

from buffered_iterator import BufferedIterator


def read_settings():
    parser = argparse.ArgumentParser(description='Scrape Minecraft servers')

    parser.add_argument('hosts')
    parser.add_argument('-t', '--threads', type=int)
    parser.add_argument('-', '--port', type=int, default=25565)
    parser.add_argument('-v', '--verbose', action='store_true')

    return parser.parse_args()


def read_ranges(hosts_file: str) -> Iterable[IPv4Network]:
    if not path.exists(hosts_file):
        raise FileNotFoundError(f'Hosts file "{hosts_file}" does not exist.')

    with open(hosts_file, 'r') as file:
        for line in file:
            yield IPv4Network(line.strip('\n'))


async def scan(ip: IPv4Address, port: int) -> PingResponse | None:
    server = JavaServer.lookup(f'{str(ip)}:{port}')

    try:
        status = await server.async_status()

        if status is not None:
            return status
    except IOError:
        return None


print_lock = Lock()


def print_thread_safe(text: str):
    print_lock.acquire()
    try:
        print(text)
    finally:
        print_lock.release()


async def scan_ips(
        ip_iterator: BufferedIterator,
        port: int,
        verbose: bool,
        handler: Callable[[PingResponse | None], None]
):
    for ip in ip_iterator:
        if verbose:
            print_thread_safe(f'[INF] Scanning {str(ip)}:{port}...')

        result = await scan(ip=ip, port=port)

        if handler is not None:
            handler(result)

        if result is None:
            continue

        print_thread_safe(json.dumps({
            'ip': str(ip),
            'port': str(port),
            'players': {
                'samples': [{
                    'id': player.id,
                    'name': player.name
                } for player in result.players.sample] if result.players.sample is not None else [],
                'online': result.players.online,
                'max': result.players.max
            },
            'version': {
                'name': result.version.name,
                'protocol': result.version.protocol
            },
            'description': result.description,
            'favicon': result.favicon,
            'latency': result.latency
        }))


def sync_scan_ips(
        **kwargs
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(scan_ips(**kwargs))
    loop.close()


def start_scan(threads: int, **kwargs):
    threads = [
        Thread(
            target=lambda: sync_scan_ips(
                **kwargs
            )
        )
        for _ in range(threads)
    ]

    for thread in threads:
        thread.start()


def handle_data(
        response: PingResponse | None,
        count_iterator: Iterator[int],
        num_addresses: int
):
    current_count = next(count_iterator)
    prev_count = current_count - 1

    old_progress = 100 * (float(prev_count) / num_addresses)
    new_progress = 100 * (float(current_count) / num_addresses)

    old_prog_int = int(old_progress)
    new_prog_int = int(new_progress)

    if old_prog_int <= new_prog_int:
        return

    print_thread_safe(f'{new_prog_int}%')


def get_all(iterables: Iterable[Iterable]) -> Iterable:
    for iterable in iterables:
        for item in iterable:
            yield item


def main():
    args = read_settings()
    ranges = list(read_ranges(args.hosts))
    threads = args.threads

    num_addresses = sum(ip_range.num_addresses for ip_range in ranges)
    long_iterable = get_all(
        ip_range.hosts() for ip_range in ranges
    )

    iterator = BufferedIterator(
        buffer_size=threads * 2,
        iterator=iter(long_iterable)
    )

    count_iterator = itertools.count()

    start_scan(
        threads=args.threads,
        ip_iterator=iterator,
        port=args.port,
        verbose=args.verbose,
        handler=lambda response: handle_data(
            response=response,
            count_iterator=count_iterator,
            num_addresses=num_addresses
        )
    )


if __name__ == '__main__':
    main()
