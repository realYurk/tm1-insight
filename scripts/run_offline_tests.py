r"""Run pytest with a temporary user home and external networking disabled.

Usage: .venv\Scripts\python.exe scripts/run_offline_tests.py -q
This is a development runner, not part of the Portable runtime.
"""
import os
import runpy
import socket
import tempfile
import requests

if __name__ == '__main__':
    os.environ['TM1_INSIGHT_HOME'] = tempfile.mkdtemp(prefix='tm1-offline-tests-')


def blocked(*args, **kwargs):
    raise RuntimeError('Offline tests: unmocked network access is forbidden')


socket.create_connection = blocked
requests.sessions.Session.send = blocked
_connect = socket.socket.connect


def loopback_only(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        return blocked()
    return _connect(self, address)


socket.socket.connect = loopback_only
if __name__ == '__main__':
    runpy.run_module('pytest', run_name='__main__')
