# RADH - RSA & Diffie-Hellman Demonstrator

**RADH** to demonstrator kryptosystemu RSA oraz wymiany kluczy Diffiego–Hellmana, realizowany w ramach przedmiotu *Podstawy kryptografii i kodowania*.

## Cel projektu

Celem jest stworzenie aplikacji edukacyjnej umożliwiającej poznanie zasad działania algorytmów RSA i Diffiego–Hellmana, wizualizację obliczeń kryptograficznych oraz przeprowadzanie eksperymentów związanych z bezpieczeństwem komunikacji.

## Zasady współpracy

Konwencje językowe, zasady branchowania, commitowania i tworzenia Pull Requestów znajdują się w pliku [CONTRIBUTING.md](CONTRIBUTING.md).

## Dostępne komponenty

- [`crypto-core/`](crypto-core/) – edukacyjne operacje kryptograficzne w C11.
- [`backend/`](backend/) – API FastAPI integrujące Python z CryptoCore przez `ctypes`.
- [`frontend/`](frontend/) – interfejs w React + TypeScript z zakładkami RSA i Diffie–Hellman.

Instrukcje budowania i uruchamiania:

- API: [`backend/README.md`](backend/README.md),
- interfejs: [`frontend/README.md`](frontend/README.md).
