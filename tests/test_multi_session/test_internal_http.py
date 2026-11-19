"""Test granicy HTTP bez otwierania socketów i bez zastępowania matematyki."""
import io
import json

import pytest

from nodes.internal_http import InternalClient, InternalError, EpochChanged, load_token

EPOCH = 'a'*32


class Socket:
    def settimeout(self, timeout):
        assert 0 < timeout <= 5

    def shutdown(self, how):
        pass


class Response:
    def __init__(self, data, status=200, headers=None):
        self.status = status
        self.stream = io.BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())
        self.headers = headers if headers is not None else {'X-Backend-Epoch':EPOCH}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.stream.read(size)


class Connection:
    def __init__(self, host, port, timeout):
        assert host == 'localhost' and timeout == 3
        self.sock = Socket()
        self.closed = False

    def connect(self):
        pass

    def request(self, method, path, body, headers):
        self.sent = method, path, body, headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@pytest.fixture
def http(monkeypatch):
    connection = Connection('localhost',8000,3)
    monkeypatch.setattr('nodes.internal_http.http.client.HTTPConnection', lambda *a, **kw: connection)
    return InternalClient('http://localhost:8000','alice','A'*43,'c'*32), connection


def test_headers_and_json(http):
    client, connection = http
    connection.response = Response({'ok':True})
    assert client.request('POST','/internal/v1/dh/sessions',EPOCH,{'value':8}) == ({'ok':True},EPOCH)
    method,path,body,headers = connection.sent
    assert path.startswith('/internal/') and method == 'POST'
    assert headers['Authorization'] == 'Bearer ' + 'A'*43
    assert headers['X-Node-Instance'] == 'c'*32 and headers['X-Backend-Epoch'] == EPOCH
    assert json.loads(body) == {'value':8} and connection.closed


@pytest.mark.parametrize('data,status,headers,kind', [
    (b'not json',200,None,InternalError), (b'x'*131073,200,None,InternalError),
    ({},200,{},InternalError), ({},200,{'X-Backend-Epoch':'b'*32},EpochChanged),
    ({'error':{'code':'UNAUTHORIZED','message':'hidden'}},401,None,InternalError),
    ({},302,None,InternalError), (b'body',204,None,InternalError),
])
def test_invalid_responses(http,data,status,headers,kind):
    client, connection = http
    connection.response = Response(data,status,headers)
    with pytest.raises(kind) as error:
        client.request('GET','/internal/v1/dh/sessions',EPOCH)
    assert 'hidden' not in str(error.value) and 'AAAA' not in str(error.value)
    assert connection.closed


def test_retry_after_bounded(http):
    client, connection = http
    connection.response = Response({'error':{'code':'RATE_LIMITED','message':'x'}},429,
                                   {'X-Backend-Epoch':EPOCH,'Retry-After':'999'})
    with pytest.raises(InternalError) as error:
        client.request('GET','/internal/v1/dh/sessions',EPOCH)
    assert error.value.retry_after == 30


def test_socket_timeout_controlled(http):
    client, connection = http
    def timeout():
        raise TimeoutError('do not leak')
    connection.getresponse = timeout
    with pytest.raises(InternalError) as error:
        client.request('GET','/internal/v1/dh/sessions',EPOCH)
    assert 'leak' not in str(error.value) and connection.closed


@pytest.mark.parametrize('url', ['http://user:pass@localhost', 'file:///tmp/x','http://localhost/path','http://localhost/?token=x'])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        InternalClient(url,'alice','A'*43,'c'*32)


def test_secret_file(tmp_path):
    path = tmp_path/'token'
    path.write_text('A'*43+'\n')
    assert load_token('alice',str(path)) == 'A'*43
    path.write_text('do-not-leak')
    with pytest.raises(ValueError) as error:
        load_token('alice',str(path))
    assert 'do-not-leak' not in str(error.value)
