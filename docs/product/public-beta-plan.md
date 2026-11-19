# RADH – plan biznesowy i zasady publicznej bety

Projekt dokumentu do issue lukasz-strama/radh#74 (parent: PBI-018). Wersja robocza do przeglądu zespołu. Ceny i regulaminy zewnętrzne należy zweryfikować przed zatwierdzeniem.

## 1. Cel i założenia

Celem publicznej bety RADH jest udostępnienie działającej wersji aplikacji szerszej grupie odbiorców, aby zebrać opinie o jej użyteczności i sprawdzić, czy wyświetla się i działa poprawnie na różnych urządzeniach i w różnych przeglądarkach. Dokument określa wymagania biznesowe i organizacyjne tej wersji.

Założenia:

- Beta ma charakter edukacyjny, a klucze RSA i DH są 32-bitowe, więc aplikacja nie służy do ochrony prawdziwych danych. Informacja o tym znajdzie się w regulaminie i na banerze w aplikacji.
- Beta jest dostępna publicznie pod własną domeną i działa stabilnie dla niewielkiej liczby jednoczesnych użytkowników.
- Dostępność jest na zasadzie „best effort”, w ogłoszonych godzinach obsługi, bez SLA 24/7.

## 2. Grupa docelowa i wartość edukacyjna

**Grupa główna:** studenci informatyki, elektroniki i cyberbezpieczeństwa, którzy znają kryptografię głównie z teorii.

**Grupa dodatkowa:** uczniowie techników i liceów z rozszerzoną informatyką, nauczyciele i prowadzący zajęcia oraz hobbyści.

**Wartość edukacyjna:** RADH pokazuje działanie wymiany kluczy Diffiego-Hellmana i RSA na interaktywnym przykładzie, wraz z demonstracją ataku MITM. Użytkownik może samodzielnie wykonać kolejne kroki i zobaczyć, gdzie atak się udaje, zamiast uczyć się samych wzorów.

## 3. Zakres funkcjonalny publicznej bety

**W becie:**

- interaktywne demo wymiany kluczy Diffiego-Hellmana,
- rozszerzenia edukacyjne RSA,
- demonstracja ataku MITM w kontrolowanym środowisku,
- generowanie kluczy w celach demonstracyjnych.

**Poza betą:**

- konta użytkowników z danymi osobowymi,
- przechowywanie cudzych kluczy lub danych,
- jakiekolwiek gwarancje bezpieczeństwa na poziomie produkcyjnym.

**Wymagania minimalne:** HTTPS (TLS 1.2/1.3), ograniczanie liczby zapytań (rate limiting), widoczny baner „edukacyjne, 32-bitowe, nie do rzeczywistych danych” bez obietnicy bezpieczeństwa RSA i DH, strona z regulaminem bety i zasadami retencji.

**Dostępność:** beta działa w ogłoszonych godzinach obsługi, bez SLA 24/7. Godziny trzeba określić i opublikować przed startem. Jest jeden backend, więc wdrożenie nowej wersji oznacza krótką przerwę, a aktywne sesje nie przeżywają wdrożenia ani restartu.

**Prywatność i retencja:** aplikacja nie ma kont ani bazy danych. Sesje są ulotne (tylko w pamięci), a token właściciela jest ograniczony do życia sesji. Logi operacyjne nie zawierają tokenów, nagłówków autoryzacji, treści żądań ani kluczy, a ich retencja docelowo wynosi 7 dni.

**Obsługa incydentów:** zespół wyznacza dyżurnego operatora i zastępcę oraz prywatny kanał kontaktu. Po otrzymaniu alarmu operator w ciągu 30 minut blokuje tworzenie nowych sesji lub zamyka ingress, w ogłoszonych godzinach obsługi. Post-mortem powstaje w ciągu 5 dni roboczych.

## 4. Porównanie wariantów hostingu

Ceny AWS i VPS są orientacyjne, a ceny SEOHOST pochodzą z oferty widocznej na stronie dostawcy (netto, promocja obejmuje pierwszy rok). Wszystkie trzeba sprawdzić przed finalizacją.

| Wariant | Koszt | Zasoby | Ograniczenia i ryzyka |
| --- | --- | --- | --- |
| AWS Free Tier – EC2 | do 200 $ kredytów dla nowych kont (100 $ na start plus do 100 $ za zadania w konsoli), plan Free do 6 miesięcy lub do wyczerpania kredytów; orientacyjnie t3.medium ok. 30 $ miesięcznie | pełny VPS 2 vCPU / 4 GiB RAM (np. t3.medium), zgodnie z planem wdrożenia, dysk EBS, Docker Compose i własny reverse proxy | tylko dla nowych kont AWS; dostępność typu z 4 GiB RAM w planie Free trzeba sprawdzić w konsoli; po 6 miesiącach konto Free jest zamykane, jeśli nie przejdzie się na plan płatny (dane przechowywane 90 dni); testy penetracyjne EC2 są dozwolone bez zgody AWS, ale DoS i flooding są zakazane |
| SEOHOST – hosting SH 3 | 97 zł netto za 1. rok (promocja), od 2. roku 257 zł netto rocznie | 80 GB NVMe, 3 vCPU, 6 GB RAM, bez limitu transferu | hosting współdzielony (PHP, LiteSpeed), dostęp SSH; prawdopodobnie bez Docker Compose i własnego reverse proxy, regulamin wobec testów do sprawdzenia |
| Tani VPS (Hetzner CX23 lub OVHcloud VPS-1) | ok. 5,5–6 € miesięcznie plus 0,50 € za IPv4 (Hetzner), podobnie OVH | 2 vCPU, 4 GB RAM, 40 GB dysku | płatne od pierwszego miesiąca, plan Hetznera bywał niedostępny po podwyżce z czerwca 2026, polityka wobec testów bezpieczeństwa do sprawdzenia |
| Serwer domowy + Cloudflare Tunnel (rozważany) | ok. 0 € (tunel darmowy), tylko prąd | zasoby własnego serwera | brak SLA, zależność od zasilania i łącza domowego, ruch tylko HTTP/HTTPS, domena musi używać DNS Cloudflare |

## 5. Szacunkowy miesięczny budżet

| Pozycja | AWS (EC2 t3.medium, 24/7) | VPS (awaryjny) |
| --- | --- | --- |
| Instancja / serwer | ok. 30 $ miesięcznie | ok. 5,5–6 € |
| Publiczny adres IPv4 | ok. 3,65 $ miesięcznie | 0,50 € |
| Dysk (EBS gp3, 30 GB) | ok. 2,4 $ miesięcznie | w cenie |
| Transfer wychodzący | 0 $ przy niewielkim ruchu | w cenie |
| Kopie zapasowe | snapshoty EBS, koszt do oszacowania | ok. 1,1 € (ok. 20% ceny serwera) |
| Domena (koszt roczny / 12) | ok. 0–5 zł | ok. 0–5 zł |
| Monitoring i alerty kosztów | AWS Budgets oraz monitoring hosta i sondy z alarmami zgodnie z planem wdrożenia, koszt do oszacowania | 0 € |
| **Razem** | **ok. 36 $ miesięcznie, ok. 218 $ za 6 miesięcy planu Free, z czego 200 $ pokrywają kredyty** | **ok. 8–10 € (ok. 35–45 zł)** |

Szacunek dotyczy regionu us-east-1 i pracy instancji przez całą dobę. Ceny jednostkowe AWS są orientacyjne i trzeba je sprawdzić w kalkulatorze AWS, bo region w Europie bywa nieco droższy. Zakładamy komplet 200 $ kredytów: 100 $ na start plus 5 zadań w konsoli po 20 $ (EC2, RDS, Lambda, Bedrock, AWS Budgets).

Wielkość maszyny (2 vCPU / 4 GiB RAM, np. t3.medium) wynika z planu wdrożenia i testów obciążeniowych z release gate. Kredyty 200 $ wystarczają wtedy na ok. 5,5 miesiąca, a cały 6-miesięczny okres planu Free kosztuje ok. 218 $, czyli ok. 18 $ ponad kredyty. Mniejsza maszyna t3.small (ok. 21 $ miesięcznie) mieściłaby się w kredytach, ale nie spełnia założenia 4 GiB RAM. W kwocie nie ma kosztu monitoringu i alarmów, który trzeba oszacować. Po 6 miesiącach konto Free jest zamykane, jeśli nie przejdzie się na plan płatny, a przejście na plan płatny pozwala wykorzystać niewydane kredyty do 12 miesięcy od rejestracji. Cenę domeny trzeba potwierdzić u rejestratora.

## 6. Architektura wdrożenia na AWS

- Jedna maszyna Linux (EC2), na której Docker Compose uruchamia pięć usług: web (Nginx z frontendem React), backend (FastAPI, jeden proces) oraz trzy procesy ról Alice, Bob i Mallory. Nginx jest jedynym punktem wejścia i kończy TLS 1.2/1.3. Nie ma bazy danych ani skalowania poziomego.
- Rozmiar maszyny: początkowo 2 vCPU / 4 GiB RAM, zgodnie z planem wdrożenia (np. t3.medium). Limity kontenerów to łącznie ok. 1,4 GiB RAM (backend 512 MiB, trzy węzły po 256 MiB, proxy 128 MiB), a ich dobór wymaga pomiaru pod obciążeniem. W konsoli trzeba sprawdzić oznaczenie „Free tier eligible”.
- Security Group: publiczny jest port 443, a port 80 służy wyłącznie do przekierowania i ACME. SSH jest dostępny tylko z adresów administratora. Port 8000, wewnętrzny 8080, panel Docker i metryki nigdy nie są publikowane.
- Stały adres Elastic IP przypięty do instancji i rekord DNS domeny.
- Certyfikat TLS (Let’s Encrypt, ACME) odnawia operator, ze sprawdzeniem ważności i próbnym odnowieniem. Nginx ustawia rate limiting (20 żądań na sekundę na IP), limit body 4 KiB i nagłówki bezpieczeństwa, a HSTS włącza się dopiero po sprawdzeniu HTTPS.
- Instancja nie zawiera cennych danych ani szerokich uprawnień IAM, a konto AWS jest zabezpieczone MFA. Dzięki temu publiczne testowanie aplikacji nie zagraża reszcie konta.
- Kopie zapasowe: snapshoty EBS oraz pliki konfiguracyjne w prywatnym repozytorium. Tokeny ról generuje operator w trzech niezależnych plikach i nie trafiają one do Git, obrazów ani logów. Sesje są ulotne i nie są kopiowane.
- AWS Budgets z alertem kosztów od pierwszego dnia oraz monitoring i alarmy z planu wdrożenia (m.in. ponad 1% błędów 5xx przez 5 minut, rola offline powyżej 30 s, certyfikat poniżej 14 dni), dostarczane do operatora.

**Ryzyka:** plan Free kończy się po 6 miesiącach lub po wyczerpaniu kredytów, a konto jest wtedy zamykane (na ponowne otwarcie przez przejście na plan płatny jest 90 dni). Kredyty dostępne są tylko dla nowych kont AWS. Publicznie testowana aplikacja jest narażona na skutki błędu konfiguracji, np. zbyt szerokich uprawnień lub otwartego portu. Możliwe są też nieoczekiwane koszty adresów IP, dysków i ruchu. Wdrożenie lub restart kasuje aktywne sesje, a jeden backend bez skalowania poziomego oznacza krótkie okna niedostępności.

## 7. Mierniki użyteczności bety (minimum trzy)

1. **Odsetek ukończonych scenariuszy demo:** jaka część użytkowników dochodzi do końca wymiany DH lub ataku MITM.
2. **Czas do pierwszego udanego użycia:** od wejścia na stronę do ukończenia pierwszego kroku demo.
3. **Ocena zrozumiałości:** krótka ankieta po demo (skala 1–5, pytanie „czy rozumiesz, jak działa wymiana kluczy?”), udostępniona jako link do zewnętrznego formularza, a nie osadzona w aplikacji, bo polityka CSP nie dopuszcza zewnętrznych skryptów.
4. **Liczba zgłoszeń błędów i sugestii na 100 sesji** (miernik uzupełniający).

Zbieranie danych bez ciasteczek, bez danych osobowych i bez identyfikatorów sesji, tokenów i adresów IP w metrykach, zgodnie z modelem zagrożeń i planem wdrożenia. Liczniki są zbierane po stronie serwera.

## 8. Proces przyjmowania błędów i sugestii

- **Kanał:** GitHub Issues w publicznym repozytorium, z szablonami `bug_report` i `feature_request`.
- **Przebieg:** zgłoszenie, triage w ciągu 7 dni (etykieta, priorytet, przypisanie), następnie trafia do backlogu Scrum Boardu.
- **Zasada:** w publicznych zgłoszeniach nie umieszcza się tokenów, danych użytkowników ani szczegółów niezałatanej podatności. Takie zgłoszenie jest przenoszone lub zamykane z odesłaniem do procedury z sekcji 9. Pierwsza beta nie ma własnego systemu zgłoszeń i korzysta z GitHuba.

## 9. Projekt polityki zgłaszania podatności

To jest poufna ścieżka, rozdzielona od zgłoszeń publicznych z sekcji 8. Kanał musi być opisany publicznie, mieć właściciela i potwierdzony odbiór próbnego zgłoszenia (kryterium G24 w release gate).

- Plik `SECURITY.md` w repozytorium.
- Włączone w GitHubie **Private vulnerability reporting** lub dedykowany adres e-mail zespołu.
- Plik `/.well-known/security.txt` na stronie.
- Zgłoszenia odbiera dyżurny operator, a pod jego nieobecność zastępca. Terminy potwierdzenia i oceny zgłoszenia zespół ustala z operatorem przed publikacją, a w razie incydentu obowiązuje procedura z sekcji 3 (reakcja w 30 minut w godzinach obsługi, post-mortem do 5 dni roboczych).
- Informacja, że projekt jest studencki i nie oferuje nagród finansowych.

## 10. Projekt zasad testów w becie i testów bezpieczeństwa

Projekt do zatwierdzenia przez zespół przed publikacją bety. W tej wersji użytkownicy mają sprawdzić poprawność działania i wyświetlania aplikacji na różnych urządzeniach, a testy bezpieczeństwa nie są autoryzowane.

**W becie wolno:**

- korzystać z aplikacji na różnych urządzeniach (telefony, tablety, komputery), systemach i przeglądarkach,
- zgłaszać błędy wyświetlania i działania publicznie, zgodnie z sekcją 8, podając urządzenie, system i przeglądarkę.

**W becie nie wolno:**

- wykonywać testów penetracyjnych, skanowania podatności ani używać zautomatyzowanych narzędzi do atakowania aplikacji,
- przeprowadzać ataków DoS i DDoS ani floodingu,
- uzyskiwać dostępu do cudzych danych ani stosować socjotechniki wobec członków zespołu.

**Podatności:** podatność znalezioną przypadkiem zgłasza się poufnie, według sekcji 9, a nie w publicznym zgłoszeniu.

**Testy zespołu:** testy izolacji, limitów i obciążenia z release gate wykonuje się na lokalnym lub jawnie autoryzowanym stagingu, bez atakowania publicznych usług. Test obciążeniowy na AWS (G21) trzeba utrzymać w granicach polityki AWS, która zakazuje floodingu żądań.

**Przyszłe testy bezpieczeństwa:** wymagałyby osobnej, pisemnej zgody zespołu i rozszerzenia tej polityki. Musiałyby też mieścić się w [polityce testów penetracyjnych AWS](https://aws.amazon.com/it/security/penetration-testing/), która pozwala testować własne instancje EC2 bez zgody AWS, ale zakazuje DoS i floodingu. Publiczne uruchomienie programu testowania bezpieczeństwa i udzielanie upoważnień do pentestów jest poza zakresem tego issue.

## 11. Mierzalne kryteria gotowości do publikacji

Kryteria gotowości określa [release gate](https://github.com/lukasz-strama/radh/blob/main/docs/security/release-gate.md): 25 mierzalnych kryteriów G01–G25, każde z dowodem. Checkbox zaznacza reviewer, GO zatwierdza właściciel #72, a brak dowodu oznacza NO-GO. Stan na 17 listopada 2026 to NO-GO. Poniżej punkty, za które odpowiada #74, oraz powiązane z nimi kryteria operacyjne.

- [ ] G24: poufny kanał zgłoszeń działa, jest opisany publicznie, ma właściciela, a odbiór próbnego zgłoszenia potwierdzono.
- [ ] G25: ostrzeżenia „edukacyjne, 32-bitowe, nie do rzeczywistych danych”, zasady bety i retencji są widoczne w aplikacji i dokumentacji, bez obietnicy bezpieczeństwa RSA i DH, z akceptacją PO.
- [ ] Opisane godziny obsługi i brak SLA 24/7.
- [ ] Wyznaczony dyżurny operator, zastępca i prywatny kanał kontaktu.
- [ ] Konto AWS założone, wybrana maszyna 2 vCPU / 4 GiB RAM, potwierdzony budżet, AWS Budgets z alertami i znana data końca planu Free.
- [ ] Infrastruktura spełnia kryteria operacyjne: publiczne tylko 443 i 80 jako przekierowanie i ACME, SSH ograniczony (G11), poprawny TLS z odnowieniem (G12), monitoring i alarmy (G18), aktualizacja i rollback (G23).
- [ ] `SECURITY.md`, szablony zgłoszeń i regulamin bety opublikowane.
- [ ] Zdefiniowane mierniki użyteczności i sposób ich zbierania zgodny z CSP i zasadami retencji.
- [ ] Projekt zasad testów zatwierdzony przez zespół.
- [ ] Pozostałe kryteria G01–G23 odebrane przez reviewera z dowodami, a GO zatwierdzone przez właściciela #72.

## 12. Mapowanie na kryteria akceptacji issue #74

| Kryterium akceptacji | Sekcja |
| --- | --- |
| Porównano minimum trzy oferty hostingu wraz z kosztami, zasobami i ograniczeniami | 4 |
| Przygotowano miesięczny budżet utrzymania aplikacji | 5 |
| Zdefiniowano minimum trzy mierniki użyteczności bety | 7 |
| Udokumentowano procedurę obsługi zgłoszeń | 8 |
| Rozdzielono publiczne zgłoszenia błędów od poufnych zgłoszeń podatności | 8 i 9 |
| Przygotowano projekt polityki testów bezpieczeństwa, przeznaczony do zatwierdzenia przed publikacją | 10 |

## 13. Źródła

Stan na 19 listopada 2026.

- [AWS Free Tier update: up to $200 in credits](https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits/) – kredyty, plan Free, termin 6 miesięcy.
- [AWS Customer Support Policy for Penetration Testing](https://aws.amazon.com/it/security/penetration-testing/) – dozwolone usługi i zakazane działania.
- [Release gate RADH](https://github.com/lukasz-strama/radh/blob/main/docs/security/release-gate.md) – kryteria G01–G25 i procedura incydentu.
- [Model zagrożeń RADH (STRIDE)](https://github.com/lukasz-strama/radh/blob/main/docs/security/threat-model.md) – ryzyka i zagrożenia związane z betą.
- [Plan wdrożenia RADH](https://github.com/lukasz-strama/radh/blob/main/docs/architecture/deployment.md) – skład usług, rozmiar maszyny 2 vCPU / 4 GiB, limity, monitoring.
- Oferta SEOHOST – zrzut ekranu ze strony dostawcy dostarczony przez zespół (ceny netto).
