import argparse
import asyncio
import itertools
import json
import sys
import threading
import time
from ipaddress import IPv4Network, IPv4Address
from os import path
from threading import Thread, Lock, Timer
from typing import Iterable, Iterator, Callable, TextIO

from mcstatus import JavaServer
from mcstatus.pinger import PingResponse

from asynchronous_counter import AsynchronousCounter
from buffered_iterator import BufferedIterator


def read_settings():
    parser = argparse.ArgumentParser(description='Scrape Minecraft servers')

    parser.add_argument('hosts')
    parser.add_argument('-t', '--threads', type=int)
    parser.add_argument('-', '--port', type=int, default=25565)
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-o', '--output', type=str)

    return parser.parse_args()


def read_ranges(hosts_file: str) -> Iterable[IPv4Network]:
    if not path.exists(hosts_file):
        raise FileNotFoundError(f'Hosts file "{hosts_file}" does not exist.')

    with open(hosts_file, 'r') as file:
        for line in file:
            yield IPv4Network(line.strip('\n'))


def scan(ip: IPv4Address, port: int) -> PingResponse | None:
    server = JavaServer.lookup(f'{str(ip)}:{port}')

    try:
        status = server.status()

        if status is not None:
            return status
    except Exception:
        return None


print_lock = Lock()


def print_thread_safe(text: str, line_start: bool = False):
    print_lock.acquire()
    try:
        if line_start:
            sys.stdout.write('\r' + text)
            sys.stdout.flush()
        else:
            print(text)
    finally:
        print_lock.release()


def scan_ips(
        ip_iterator: BufferedIterator,
        port: int,
        verbose: bool,
        handler: Callable[[PingResponse | None], None],
        writer: Callable[[str], None]
):
    for ip in ip_iterator:
        if verbose:
            print_thread_safe(f'[INF] Scanning {str(ip)}:{port}...')

        result = scan(ip=ip, port=port)

        if handler is not None:
            handler(result)

        if result is None:
            continue

        output_text = json.dumps({
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
        })

        writer(output_text)


def start_scan(threads: int, status_updater: Callable[[], None], **kwargs):
    threads = [
        Thread(
            target=lambda: scan_ips(
                **kwargs
            )
        )
        for _ in range(threads)
    ]

    for thread in threads:
        thread.start()

    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(1)
            status_updater()
    except KeyboardInterrupt:
        print('Cancelling...')
        for thread in threads:
            thread.join()



def handle_data(
        response: PingResponse | None,
        counter: AsynchronousCounter,
        result_counter: AsynchronousCounter
):
    counter.increment()
    if response is not None:
        result_counter.increment()


def update_status(
        current_count: int,
        results: int,
        num_addresses: int
):
    current_percentage = (100 * current_count) // num_addresses

    prog_true = current_percentage // 2
    prog_false = 50 - prog_true

    prog_str = '[' + prog_true * '#' + prog_false * '-' + \
               f'] {current_percentage}% (scanned {current_count} / {num_addresses}) {results} found'

    print_thread_safe(
        prog_str,
        line_start=True
    )


def get_all(iterables: Iterable[Iterable]) -> Iterable:
    for iterable in iterables:
        for item in iterable:
            yield item


def write_result(result: str, output_file: TextIO, output_lock: Lock):
    if output_file is None:
        print_thread_safe(result)
    else:
        with output_lock:
            output_file.write(result + '\n')


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

    counter = AsynchronousCounter()
    result_counter = AsynchronousCounter()

    file_lock = Lock() if args.output is not None else None
    file_ref = open(args.output, 'a') if args.output is not None else None

    start_scan(
        threads=args.threads,
        ip_iterator=iterator,
        port=args.port,
        verbose=args.verbose,
        handler=lambda response: handle_data(
            response=response,
            counter=counter,
            result_counter=result_counter
        ),
        writer=lambda output_text: write_result(
            result=output_text,
            output_file=file_ref,
            output_lock=file_lock
        ),
        status_updater=lambda: update_status(
            current_count=counter.value,
            results=result_counter.value,
            num_addresses=num_addresses
        )
    )

    print(f'Done. Found {result_counter.value} servers.')


if __name__ == '__main__':
    main()
