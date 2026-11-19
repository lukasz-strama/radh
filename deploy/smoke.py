"""Ręczny smoke prawdziwego Compose v2 na loopback; nie zastępuje QA #71."""
import argparse
import json
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class SmokeError(Exception):
    """Wyłącznie bezpieczna etykieta kroku, bez treści odpowiedzi i poświadczeń."""


def check(condition: bool, label: str) -> None:
    if not condition:
        raise SmokeError(label)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, url: str):
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise SmokeError('Wymagany lokalny URL HTTP bez ścieżki i poświadczeń.')
        self.base = url.rstrip('/')

    def request(self, method: str, path: str, *, body=None, token=None, key=None,
                epoch=None, expected=(200,), retry=True):
        headers = {'Content-Type': 'application/json', 'Origin': self.base}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if key:
            headers['Idempotency-Key'] = key
        if epoch:
            headers['X-Backend-Epoch'] = epoch
        payload = None if body is None else json.dumps(body).encode()
        deadline = time.monotonic() + 45
        # Osobny opener na wywołanie: także przy równoległych startach.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        while True:
            request = Request(self.base + path, data=payload, headers=headers, method=method)
            try:
                response = opener.open(request, timeout=5)
            except HTTPError as error:
                response = error
            except (URLError, OSError, TimeoutError) as error:
                if isinstance(error, PermissionError) or isinstance(getattr(error, 'reason', None), PermissionError):
                    raise SmokeError('Środowisko blokuje otwieranie socketów.') from None
                # Stałe klucze/id sesji zachowują idempotencję także przy utracie odpowiedzi.
                if not retry or time.monotonic() >= deadline:
                    raise SmokeError('Brak połączenia z lokalnymi usługami.') from None
                time.sleep(1)
                continue
            with response:
                status = response.code
                raw = response.read(131073)
                check(len(raw) <= 131072, 'Za duża odpowiedź.')
                response_headers = response.headers
            if retry and status in (429, 503) and time.monotonic() < deadline:
                value = response_headers.get('Retry-After', '1')
                time.sleep(min(30, max(1, int(value))) if value.isdigit() else 1)
                continue
            check(status in expected, f'{method}: nieoczekiwany status HTTP {status}.')
            check('no-store' in response_headers.get('Cache-Control', ''), 'Brak no-store.')
            if not raw or method == 'HEAD':
                return status, None, response_headers
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                # TRACE i błędy wbudowane Nginx mogą zwracać HTML.
                check(status >= 400, 'Niepoprawny JSON sukcesu.')
                data = None
            return status, data, response_headers


def main() -> None:
    parser = argparse.ArgumentParser(description='Lokalny smoke Compose DH v2 i RSA.')
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--diagnostics', action='store_true')
    args = parser.parse_args()
    client = Client(args.url)
    root = '/api/v2/dh/sessions'
    probe = root + '/' + 'a' * 32
    for method, path, status in [
        ('GET','/internal',403), ('GET','/internal/health/ready',403),
        ('GET','/api/v1/dh/sessions/current',404), ('POST','/api/v1/dh/sessions',404),
        ('POST','/api/v1/dh/nodes/alice/heartbeat',404),
        ('POST',probe+'/messages',404), ('POST',probe+'/messages/bob-public/ack',404),
        ('POST',probe+'/interceptions/alice-public/forward',404),
        ('POST',probe+'/diagnostics',403), ('POST',probe+'/diagnostics/mallory',403),
        ('PUT',probe,403), ('HEAD','/api/v2/dh/nodes',403),
        ('GET',root+'/BAD',404), ('GET','/openapi.json',403),
        ('GET','/docs',403), ('GET','/redoc',403),
    ]:
        client.request(method, path, expected=(status,))
    print('Allowlista proxy: OK')
    _, key, _ = client.request('POST','/api/v1/rsa/demo/keygen',body={'p':61,'q':53,'e':17})
    check(key == {'n':3233,'e':17,'d':2753,'phi':3120}, 'RSA keygen.')
    _, cipher, _ = client.request('POST','/api/v1/rsa/demo/encrypt',body={
        'message':65,'public_exponent':17,'modulus':3233})
    check(cipher == {'ciphertext':2790}, 'RSA encrypt.')
    print('RSA/keygen: OK')
    deadline = time.monotonic()+40
    while True:
        _, presence, headers = client.request('GET','/api/v2/dh/nodes')
        epoch = headers.get('X-Backend-Epoch','')
        check(bool(re.fullmatch('[0-9a-f]{32}',epoch)), 'Epoch obecności.')
        if all(presence[role]['online'] is True for role in ('alice','bob','mallory')):
            break
        check(time.monotonic() < deadline, 'Brak rejestracji węzłów.')
        time.sleep(2)
    created = []
    try:
        creation_keys = [secrets.token_urlsafe(32),secrets.token_urlsafe(32)]
        for mode, creation_key in zip(('normal','mitm'), creation_keys):
            body = dict(prime=23,generator=5,mode=mode,diagnostics_enabled=True)
            # Opt-in właściciela jest celowo true także przy lokalnym RADH_DIAGNOSTICS=0.
            _, result, _ = client.request('POST',root,body=body,key=creation_key,epoch=epoch,expected=(201,))
            sid, token = result['session']['session_id'], result['session_token']
            check(bool(re.fullmatch('[0-9a-f]{32}',sid)) and bool(re.fullmatch('[A-Za-z0-9_-]{43}',token)), 'Format poświadczenia.')
            created.append((sid,token))
            if mode == 'normal':
                _, repeated, _ = client.request('POST',root,body=body,key=creation_key,epoch=epoch,expected=(201,))
                check(repeated == result, 'Idempotencja create.')
        check(created[0][0] != created[1][0] and created[0][1] != created[1][1]
              and creation_keys[0] != creation_keys[1], 'Izolacja poświadczeń.')
        path = root+'/'+created[0][0]
        _, before, _ = client.request('GET',path,token=created[0][1])
        client.request('POST',path+'/start',expected=(401,))
        client.request('POST',path+'/cancel',token=created[1][1],expected=(404,))
        _, after, _ = client.request('GET',path,token=created[0][1])
        check(before == after, 'Nieautoryzowana mutacja stanu.')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(client.request,'POST',root+'/'+sid+'/start',token=token)
                       for sid,token in created]
            for future in futures:
                future.result()
        deadline = time.monotonic()+40
        overlap = False
        while True:
            states = [client.request('GET',root+'/'+sid,token=token)[1] for sid,token in created]
            overlap |= all(s['status'] == 'running' for s in states)
            check(all(s['status'] in ('running','completed') for s in states), 'Nieudany protokół DH.')
            if all(s['status'] == 'completed' for s in states):
                break
            check(time.monotonic() < deadline, 'Timeout DH.')
            time.sleep(2)
        print('Normal i MITM zakończone; równoległe starty: OK')
        print('Zaobserwowano oba running.' if overlap else
              'Nie zaobserwowano obu running: nakładanie stanów nie zostało udowodnione.')
        for index, (sid, token) in enumerate(created):
            path = root+'/'+sid
            state = states[index]
            check(state['session_id'] == sid and state['backend_epoch'] == epoch, 'Tożsamość sesji.')
            check(state['participants'] == {'alice':'received','bob':'received'}, 'ACK obu uczestników.')
            check(len(state['messages']) == 2 and all(m['status']=='processed' for m in state['messages']), 'Wiadomości.')
            check({m['message_id'] for m in state['messages']} == {'alice-public','bob-public'}, 'ID wiadomości.')
            check(len(state['interceptions']) == index*2, 'Izolacja przechwyceń.')
            check(all(type(m['public_value']) is int and 1 <= m['public_value'] < 23
                      for m in state['messages']), 'Zakres wartości publicznych.')
            check(all(i['status']=='processed' and 1 <= i['original_value'] < 23
                      and 1 <= i['delivered_value'] < 23 for i in state['interceptions']), 'Przechwycenia MITM.')
            _, history, _ = client.request('GET',path+'/events?after=0&limit=32',token=token)
            check(history['session_id'] == sid and history['backend_epoch'] == epoch, 'Izolacja historii.')
            events = history['events']
            check([e['sequence'] for e in events] == list(range(1,len(events)+1)), 'Sekwencja zdarzeń.')
            check(events[0]['type']=='session_created' and events[-1]['type']=='session_completed', 'Historia protokołu.')
            deadline = time.monotonic()+25
            while True:
                _, diag, _ = client.request('GET',path+'/diagnostics',token=token)
                _, mallory, _ = client.request('GET',path+'/diagnostics/mallory',token=token)
                values = list(diag.values()) + (list(mallory.values()) if index else [])
                if not args.diagnostics or all(v is not None for v in values):
                    break
                check(time.monotonic()<deadline,'Brak diagnostyki w oknie raportowania.')
                time.sleep(2)
            if args.diagnostics:
                check(all(type(v) is int and 1 <= v < 23 for v in values), 'Zakres diagnostyki.')
                if not index:
                    check(all(v is None for v in mallory.values()), 'Mallory w sesji normal.')
                if index:
                    check(diag['alice']==mallory['shared_with_alice'] and diag['bob']==mallory['shared_with_bob'], 'Zgodność MITM.')
                else:
                    check(diag['alice']==diag['bob'], 'Zgodność normal.')
            else:
                check(all(v is None for v in [*diag.values(),*mallory.values()]), 'Ujawniona diagnostyka bez opt-in węzłów.')
            check(not any(k in state for k in ('shared_secret','alice_secret','bob_secret','x','y')), 'Sekret w SessionView.')
        # Usunięcie jednego rekordu nie zmienia ukończonego protokołu drugiego.
        survivor_path = root+'/'+created[1][0]
        _, before, _ = client.request('GET',survivor_path,token=created[1][1])
        for _ in range(2):
            client.request('DELETE',root+'/'+created[0][0],token=created[0][1],expected=(204,))
        client.request('GET',root+'/'+created[0][0],token=created[0][1],expected=(410,))
        _, after, _ = client.request('GET',survivor_path,token=created[1][1])
        check(before==after,'DELETE zmieniło inną sesję.')
        print('Autoryzacja, idempotencja, izolacja i diagnostyka: OK')
    finally:
        cleanup_failed = False
        for sid,token in created:
            try:
                client.request('DELETE',root+'/'+sid,token=token,expected=(204,404,410))
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise SmokeError('Nie udało się posprzątać wszystkich własnych sesji; zadziała TTL.')
    print('Cleanup własnych sesji: OK')


if __name__ == '__main__':
    try:
        main()
    except SmokeError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('Smoke przerwany: sprawdź dostępność lokalnego proxy i usług (bez wypisywania odpowiedzi).') from None
