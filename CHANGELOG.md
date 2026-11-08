# Zmiany

## 1.0.14 — 2026-11-08
- Mapa projektu: przy każdej sygnaturze numer linii (`# L120`), więc model czyta od razu właściwy fragment.
- Pliki od 800 linii dostają sekcję „Mapa pliku” ze wszystkimi funkcjami i metodami, także prywatnymi
  (bez dunderów poza `__init__`), pogrupowanymi po klasach, najwyżej 150 pozycji.
- Opis modułu pomija linie z samą nazwą pliku lub numerem wersji („v2.0”, „v4.0 (przepisane od zera)”)
  i bierze następną sensowną linię docstringu.
- Moduł powyżej 5000 linii bez funkcji i klas (np. dane base64) jest oznaczony w INDEX jako „(dane)”.
- Poprawka: odświeżanie mapy po turze startuje, zanim model zostanie oznaczony jako wolny
  (wcześniej rzadko ścigało się z zamykaniem programu).

## 1.0.13 — 2026-11-08
- Mapa projektu (`.trybunai/mapa`, przycisk „Mapa” na górze): INDEX.md z listą plików i notatka dla każdego
  modułu Pythona (pierwsza linia opisu, publiczne sygnatury, „Zależy od” / „Używany przez” z importów).
  Odświeżana przyrostowo, sekcja „Uwagi (ręczne)” nigdy nie jest nadpisywana, folder działa jako vault
  Obsidiana. Bez adresów IP, haseł i wartości domyślnych z tekstem; katalogi z danymi do pominięcia
  w Ustawieniach (domyślnie „obiekty”).
- Nowa sesja modelu dostaje wskazówkę „zacznij od mapy” i ostatnie zmiany zamiast przeszukiwać program.
- Dziennik ZMIANY.md (30 ostatnich wpisów): po każdej turze z edycją kto, co i w których plikach.
  Trwająca sesja innego modelu dostaje nowe wpisy przy swojej następnej turze.
- „Pliki startowe”: tworzy brakujące CLAUDE.md, AGENTS.md i GEMINI.md z odsyłaczem do REGULY.md i mapy.

## 1.0.12 — 2026-11-08
- „O programie” (link na dole): wersja, autor, licencja MIT, linki do GitHuba i strony oraz opis
  wszystkich elementów programu.
- Aktualizacje z poziomu programu: sprawdzanie najnowszego wydania na GitHubie (też po cichu przy starcie,
  z dopiskiem „nowa wersja” przy linku) i aktualizacja jednym przyciskiem: pobranie exe, weryfikacja
  sumy SHA-256 z GitHuba, podmiana pliku i ponowne uruchomienie. Stary exe zostaje jako kopia i znika
  przy następnym starcie. Aktualizowana jest uruchomiona kopia programu.

## 1.0.11 — 2026-11-08
- Sprawdzanie po debacie kończy się werdyktem: AKCEPTUJĘ, UWAGI albo NIE MOGĘ SPRAWDZIĆ (plakietka przy
  odpowiedzi). Brak werdyktu nigdy nie liczy się jako akceptacja. Przy uwagach wdrażający poprawia
  i sprawdzający oceniają ponownie, najwyżej 0–2 razy (ustawienie w menu Debata). Na końcu podsumowanie;
  ostatnie słowo należy do użytkownika.
- Role modeli w Ustawieniach (np. „inżynier”, „tester”, „pedagog”), dopisywane do każdej wiadomości modelu.
- Kartka „chciał zrobić coś ponad uprawnienia”: lista zablokowanych działań (Claude, Haiku, Antigravity)
  i przycisk jednorazowej zgody z ponowieniem. Stałe uprawnienia się nie zmieniają. Nie dotyczy debat
  i sprawdzania, które są tylko do odczytu z założenia.

## 1.0.10 — 2026-11-08
- Górny pasek: Instalacja, Zdalnie, Ustawienia, Nowa rozmowa. Wybór uprawnień przeniesiony na dół,
  zaraz za przyciskami modeli, nad polem wiadomości.
- Ustawienia: model wybierany z listy zamiast wpisywania. Listy z zainstalowanych CLI (Claude: aliasy
  i dodatkowe modele z jego ustawień, Codex: jego lista modeli, Antigravity: `agy models`), przycisk
  „Odśwież listy modeli” i opcja „Inny (wpisz)…”.

## 1.0.9 — 2026-11-08
- Pamięć projektu ma sekcję „Nie ruszać”: rzeczy ustalone przez użytkownika, które łatwo przypadkiem
  zepsuć. Aktualizacja pamięci przenosi je bez zmian, a modele traktują je jak twarde zasady.
- „Zapisz stan teraz” w Ustawieniach: aktualizuje pamięć bez resetowania sesji (np. przed przejściem
  na inny komputer).
- „Nowa rozmowa” najpierw zapisuje stan do pamięci, potem archiwizuje czat. Nieudany zapis nie blokuje
  nowej rozmowy, tylko pokazuje ostrzeżenie.

## 1.0.8 — 2026-11-07
- Pamięć projektu (`.trybunai/pamiec.md`): zwięzłe ustalenia, stan prac i preferencje. Każda nowa
  sesja modelu (także po „Nowa rozmowa”) startuje od niej zamiast od całej historii.
- „Świeża sesja” najpierw aktualizuje pamięć (robi to model Promptera, domyślnie Haiku, z tekstu czatu),
  potem zastępuje długą sesję modelu pamięcią i ostatnią wymianą.
- Automatyczna świeża sesja po przekroczeniu 150 tys. tokenów kontekstu (domyślnie włączona,
  wyłącznik w Ustawieniach). Gdy pamięci nie uda się zaktualizować, sesja zostaje bez zmian.
- Pamięć widoczna i edytowalna w Ustawieniach.

## 1.0.7 — 2026-11-07
- Menu debaty (przycisk „Debata”): temat, uczestnicy, liczba rund, kto zaczyna, kto kończy,
  kto wdraża po debacie (ze swoimi uprawnieniami) i opcjonalne sprawdzenie wdrożenia przez pozostałych.
  Ostatnie ustawienia są zapamiętywane.
- Debata odmawia startu, gdy wybrany wdrażający ma „Tylko odczyt”; ostrzega, gdy temat każe coś
  wdrożyć, a nikt nie jest wybrany do wdrożenia.
- Przy odpowiedziach Claude, Haiku i Antigravity: model, rozmiar kontekstu i liczba kroków.
- Gdy sesja modelu przekroczy 150 tys. tokenów: ostrzeżenie z przyciskiem „Świeża sesja”
  (model dostaje wtedy ostatnie wiadomości czatu, także swoje).
- Claude i Haiku bez skilli i poleceń slash: około 25% mniej stałego narzutu na każdy krok.
- Błąd „authentication failed / please sign in” podpowiada logowanie przez „Instalacja”.

## 1.0.6 — 2026-11-02
- Ustawienia: sekcja „Plany i limity” z planem i zużyciem limitów Claude/Haiku, Codexa i Antigravity,
  z paskami i godziną odnowienia. Sprawdzanie nie zużywa limitów: Claude z odpowiedzi modelu,
  Codex z jego logów sesji, Antigravity przez `agy -p=/usage`.

## 1.0.5 — 2026-11-02
- Nowy model: Antigravity CLI (`@antigravity`, `@agy`), następca Gemini CLI dla kont Google
  (darmowy z limitami). Instalator TrybunAI instaluje go oficjalnym skryptem Google i otwiera logowanie.
- Uprawnienia Antigravity ustawiane jawnie, bo jego tryb domyślny zapisuje pliki bez pytania:
  odczyt = tylko czytanie, edycja = czytanie i zapis bez poleceń, pełny dostęp = wszystko.
- Gemini CLI jest opcjonalny: widoczny tylko, gdy jest zainstalowany (działa już tylko z kluczem API),
  i nie jest instalowany automatycznie.

## 1.0.4 — 2026-11-02
- Okno logowania zamyka się samo, gdy logowanie się powiedzie. Gemini po zalogowaniu
  zostawał w swoim czacie i instalator czekał bez końca, przez co aplikacja wyglądała na zawieszoną.

## 1.0.3 — 2026-11-02
- Nowa ikona exe rysowana skryptem `draw_icon.py` (`assets/icon-source.png`).
- Numer wersji w tytule okna; zasady numerowania w `CLAUDE.md`.

## 1.0.0 — 2026-11-02
- Pierwsza wersja na GitHubie.
