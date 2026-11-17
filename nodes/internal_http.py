"""Ograniczony klient internal: bez redirectów, proxy środowiskowych i logowania body."""
import http.client
import json
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


class InternalError(Exception):
    def __init__(self, status: int = 0, code: str = 'NETWORK_ERROR', retry_after: float = 0):
        super().__init__('Błąd komunikacji internal.')
        self.status, self.code, self.retry_after = status, code, retry_after


class EpochChanged(InternalError):
    pass


def load_token(role: str, path: str) -> str:
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(129)
        if len(raw) > 128 or role not in ('alice', 'bob', 'mallory'):
            raise ValueError()
        token = raw.decode('ascii').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ValueError()
        return token
    except (OSError, ValueError, UnicodeError):
        raise ValueError('Niepoprawny plik poświadczenia roli.') from None


class InternalClient:
    def __init__(self, url: str, role: str, token: str, instance_id: str):
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ('', '/') or role not in ('alice', 'bob', 'mallory')
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
                or not re.fullmatch(r'[0-9a-f]{32}', instance_id)):
            raise ValueError('Niepoprawna konfiguracja internal.')
        self._url, self.role, self._token, self.instance_id = parsed, role, token, instance_id
        self._slots = threading.BoundedSemaphore(4)

    def request(self, method: str, path: str, epoch: str | None, body: dict | None = None):
        headers = {'Authorization': 'Bearer ' + self._token,
                   'Content-Type': 'application/json', 'X-Node-Instance': self.instance_id}
        if epoch is not None:
            headers['X-Backend-Epoch'] = epoch
        payload = None if body is None else json.dumps(body).encode()
        if payload is not None and len(payload) > 4096:
            raise InternalError(code='INVALID_REQUEST')
        connection_type = (http.client.HTTPSConnection if self._url.scheme == 'https'
                           else http.client.HTTPConnection)
        with self._slots:
            connection = connection_type(self._url.hostname, self._url.port, timeout=3)
            deadline = time.monotonic() + 5
            active_socket = []
            def abort():
                if active_socket:
                    try:
                        active_socket[0].shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass  # Połączenie mogło już zostać zamknięte.
            timer = threading.Timer(5, abort)
            timer.daemon = True
            timer.start()
            try:
                connection.connect()
                active_socket.append(connection.sock)
                connection.sock.settimeout(max(.001, deadline - time.monotonic()))
                connection.request(method, path, body=payload, headers=headers)
                response = connection.getresponse()
                received_epoch = response.getheader('X-Backend-Epoch', '')
                if not re.fullmatch(r'[0-9a-f]{32}', received_epoch):
                    raise InternalError(code='INVALID_RESPONSE')
                if epoch is not None and epoch != received_epoch:
                    raise EpochChanged(code='BACKEND_EPOCH_MISMATCH')
                raw = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    active_socket[0].settimeout(remaining)
                    chunk = response.read1(min(8192, 131073 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > 131072:
                        raise InternalError(code='INVALID_RESPONSE')
                if response.status == 204:
                    if raw:
                        raise InternalError(code='INVALID_RESPONSE')
                    return None, received_epoch
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise InternalError(code='INVALID_RESPONSE') from None
                if response.status >= 400:
                    if (not isinstance(data, dict) or set(data) != {'error'}
                            or not isinstance(data['error'], dict)
                            or set(data['error']) != {'code', 'message'}
                            or not all(isinstance(v, str) for v in data['error'].values())):
                        raise InternalError(code='INVALID_RESPONSE')
                    retry = response.getheader('Retry-After', '0')
                    delay = min(30, int(retry)) if retry.isdigit() else 0
                    raise InternalError(response.status, data['error']['code'], delay)
                if response.status != 200:
                    raise InternalError(code='INVALID_RESPONSE')
                return data, received_epoch
            except (OSError, http.client.HTTPException):
                raise InternalError() from None
            finally:
                timer.cancel()
                timer.join()
                connection.close()
