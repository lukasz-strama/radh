"""Inicjalizacja plików dla rootful Docker na Linux, bez nadpisywania tokenów."""
import os
from pathlib import Path
import re
import secrets
import stat
import sys

ROLES = ('alice', 'bob', 'mallory')


def initialize(directory: Path) -> None:
    if os.geteuid() != 0:
        raise ValueError('Uruchom: sudo python3 deploy/init_secrets.py (wymagany chown na UID/GID 10001).')
    if directory.parent.is_symlink() or directory.is_symlink():
        raise ValueError('Katalog sekretów nie może być dowiązaniem.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Katalog sekretów musi należeć do root i mieć tryb 0700.')
    tokens = set()
    # Najpierw sprawdź istniejące pliki; żadnego nie nadpisuj ani nie naprawiaj w ciszy.
    for role in ROLES:
        path = directory / role
        if path.is_symlink():
            raise ValueError('Plik sekretu nie może być dowiązaniem.')
        if not path.exists():
            continue
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (10001, 10001, 0o400)):
            raise ValueError('Istniejący sekret wymaga właściciela 10001:10001 i trybu 0400.')
        raw = path.read_bytes()
        if len(raw) > 128 or not re.fullmatch(rb'[A-Za-z0-9_-]{43}\n?', raw) or raw.strip() in tokens:
            raise ValueError('Niepoprawne lub współdzielone poświadczenia; nie zmieniono istniejących plików.')
        tokens.add(raw.strip())
    for role in ROLES:
        path = directory / role
        if path.exists():
            continue
        token = secrets.token_urlsafe(32).encode()
        while token in tokens:
            token = secrets.token_urlsafe(32).encode()
        # O_EXCL blokuje przypadkowe nadpisanie, także przy równoległej inicjalizacji.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 10001, 10001)
            os.fchmod(stream.fileno(), 0o400)
            stream.write(token + b'\n')
        tokens.add(token)


if __name__ == '__main__':
    try:
        initialize(Path(__file__).resolve().parents[1] / '.local' / 'secrets')
    except (OSError, ValueError) as error:
        # Błędy systemowe nie wypisują ścieżek ani zawartości plików.
        message = str(error) if isinstance(error, ValueError) else 'Nie można zainicjalizować sekretów.'
        raise SystemExit(message) from None
    print('Sekrety gotowe; istniejące pliki pozostawiono bez zmian.')
