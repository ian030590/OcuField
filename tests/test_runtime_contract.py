from pathlib import Path
import subprocess
import sys


def test_offline_socket_guard():
    subprocess.run(
        [sys.executable, '-c', """
import socket
import sys
from run_ocufield import block_socket_access

sys.addaudithook(block_socket_access)
with socket.socket() as tcp, socket.socket(type=socket.SOCK_DGRAM) as udp:
    address = ('127.0.0.1', 9)
    checks = [
        lambda: tcp.connect(address),
        lambda: tcp.connect_ex(address),
        lambda: udp.sendto(b'guard test', address),
        lambda: socket.getaddrinfo(*address),
    ]
    for check in checks:
        try:
            check()
        except OSError as error:
            assert str(error) == 'OcuField runs offline'
        else:
            raise AssertionError('a network operation was allowed')
"""],
        cwd=Path(__file__).resolve().parents[1], check=True,
    )
