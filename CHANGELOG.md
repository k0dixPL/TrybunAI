# Zmiany

## 1.0.29 — 2026-11-10
- Specjaliści: zespół jak w grupie na komunikatorze. Przycisk ＋ na dolnym pasku dodaje członka zespołu
  z `@uchwytem`, nazwą, silnikiem (Claude, Codex, Antigravity), modelem, rolą i kolorem. Każdy ma własną
  rozmowę, swój kolor w czacie, pigułce i statystykach, bierze udział w debatach i może być w @wszyscy.
  Specjaliści należą do projektu (`.trybunai/chat.json`); usunięty znika z paska, ale zostaje w historii.
- Prawy klik na przycisku modelu otwiera edytor roli, modelu i koloru, także dla wbudowanych modeli.
- Ustawienia → Modele: lista „Zespół” z przyciskami „Edytuj” zamiast osobnych pól modelu i roli.
  Rola może mieć do 1000 znaków (wcześniej 400).
- README i strona projektu: opis specjalistów, nowe zrzuty czatu, edytora i zakładki Modele.

## 1.0.28 — 2026-11-10
- Pola liczbowe (liczba rund w debacie, limit tekstu PDF) mają ciemny styl jak reszta pól; wcześniej
  były białe z jasnym, prawie niewidocznym tekstem.
- Zakładka „O programie” otwarta z Ustawień pokazuje wersję i autora (wcześniej tylko przez „?”).
- Przycisk „Nowa rozmowa” po użyciu wraca do napisu zamiast ikony 📄.
- Pomoc nie mówi już o zmianie folderu kliknięciem ścieżki ani o ikonie 📄.
- Nazwa projektu na pasku nie jest ucinana, gdy świeci pigułka pracy; ustępuje opis czynności w pigułce.
- README: nowe zrzuty (główne okno, debata, podsumowanie z wyborem, Modele, Statystyki, O programie)
  i opis pigułki pracy, zaznaczania tekstu oraz zasady „jeden projekt, jedno okno”.

## 1.0.27 — 2026-11-10
- Nazwa projektu jest na środku górnego paska, pogrubiona. Kliknięcie otwiera folder projektu w Eksploratorze.
- Usunięty wybór innego folderu z okna: jedno okno to jeden projekt, inny projekt to inne okno.

## 1.0.26 — 2026-11-10
- Tekst w czacie można zaznaczyć i skopiować. Wcześniej pywebview blokował zaznaczanie w całym oknie.
- Strona projektu (GitHub Pages) opisuje Haiku, nowe funkcje i zakładki Ustawień.

## 1.0.25 — 2026-11-10
- **Gemini usunięty:** agent Gemini CLI, alias `@gemini`, jego domyślne włączanie w `@wszyscy`, parser, wiersz w liście modeli i kolory w statystykach. Darmowe limity Gemini się kończyły. Modele Antigravity o nazwach „gemini-…” zostają, bo to nazwy modeli w Antigravity.
- Mechanizm „opcjonalnych” modeli (widocznych tylko przy zainstalowanym CLI) zniknął, bo był używany tylko przez Gemini.
- README przebudowany: spis treści, tabele ustawień i opis zdalnego sterowania zgodne z aktualnym programem.

## 1.0.24 — 2026-11-10
- **Załączniki PDF:** tekst z PDF-a jest wyciągany (biblioteka pypdf) i dokładany do prompta każdego modelu. Dzięki temu w trybie „Tylko czytaj” modele czytają PDF-y, czego wcześniej nie potrafiły. Treść jest ucinana do limitu.
- **Limit tekstu PDF:** Ustawienia → Modele, pole „Tekst z załączonego PDF-a, najwyżej znaków”. Domyślnie 30 000, zakres 0–500 000. Wartość 0 wyłącza dołączanie tekstu PDF-ów.
- **O programie w Ustawieniach:** zakładka „O programie” zawiera dane programu, sekcję aktualizacji (sprawdź ponownie, zaktualizuj) i pełny opis działania: folder projektu, czat i @-wzmianki, uprawnienia, debatę, Prompter, pamięć projektu, mapę, statystyki i zdalne sterowanie.
- **Przycisk „?”:** na górnym pasku, obok „Nowa rozmowa”. Otwiera zakładkę „O programie” w Ustawieniach. Gdy jest nowsza wersja, pokazuje kropkę, a podpowiedź mówi, którą.
- **Pigułka „Pamięć”:** na górnym pasku pokazuje się podczas aktualizacji pamięci projektu, tak jak pigułki modeli.
- Animacje pigułek i poświaty wyłączają się przy ustawieniu Windows „Efekty animacji” (ograniczenie ruchu).

## 1.0.23 — 2026-11-09
- Ustawienia mają zakładki: Modele, Pamięć, Mapa, Statystyki, Zdalnie i Limity. Mapa, Statystyki
  i Zdalnie zniknęły z górnego paska i są teraz w Ustawieniach. Okno jest szersze (do 1000 px),
  a przycisk zamknięcia (✕) jest w nagłówku, zawsze widoczny; przewija się tylko treść zakładki.
  Zmiany zapisują się przy zamknięciu, także przez Esc. Gdy zdalne sterowanie jest włączone,
  przycisk Ustawienia na górnym pasku jest podświetlony. Haiku nie ma już wyboru modelu, tylko rolę.

## 1.0.22 — 2026-11-09
- Wraca pigułka „pracuje” na górnym pasku, obok poświaty dymka: kolor modelu, czas pracy, bieżąca
  czynność, światło okrążające ramkę, wejście z rozbłyskiem i wygaszenie na końcu. Kliknięcie przewija
  do odpowiedzi, „✕” zatrzymuje model. Przy kilku modelach naraz pigułki są krótsze.
- Pigułka i „zaznacz wszystkie / odznacz” w karcie wyboru to prawdziwe przyciski (działają z klawiatury).
- Werdykty mają własne kolory i ikony (✓ akceptuję, ! uwagi, ? nie mógł sprawdzić), osobne od kolorów
  modeli. Przycisk Debata i karta wyboru są w neutralnym kolorze akcentu zamiast żółtego Haiku.
- Górny pasek: Instalacja i Zdalnie wyciszone (rzadko używane), „Nowa rozmowa” opisana słowami zamiast 📄.
- Porządki: kolor akcentu w jednej zmiennej, mniej rozmiarów czcionek, „1 runda / 2 rundy / 5 rund”.

## 1.0.21 — 2026-11-09
- Stop kliknięty tuż po zakończeniu odpowiedzi nie zabija już następnej odpowiedzi tego modelu.
- Uszkodzony `chat.json` nie blokuje startu i nie kasuje historii: plik trafia do `chat-uszkodzony-*.json`, a czat startuje pusty.
- Błąd w jednym zdarzeniu interfejsu nie zatrzymuje już przesyłania zdarzeń do okna.

## 1.0.20 — 2026-11-09
- Poświata pracy pulsuje teraz po bokach aktywnego dymka, za jego treścią, zamiast na środku okna.
- W trybie ograniczonego ruchu pozostaje widoczna jako stała poświata.

## 1.0.19 — 2026-11-09
- Poświata pracy modelu jest jaśniejsza, pulsuje szybciej i ma kształt szerokiego, płaskiego pasa
  światła przez środek okna (jak horyzont).

## 1.0.18 — 2026-11-09
- Usunięto animowany pasek pracy z nagłówka. Podczas pracy modelu całe okno delikatnie pulsuje
  poświatą w kolorze aktywnego modelu; efekt respektuje ustawienie ograniczonego ruchu.

## 1.0.17 — 2026-11-09
- Debata z wdrażaniem nie przechodzi już sama do zmian w plikach. Model, który ma wdrażać, najpierw pisze
  (tylko do odczytu) podsumowanie: na czym stanęło, gdzie zostały różnice zdań, oraz ponumerowaną listę
  propozycji. Pod podsumowaniem pojawia się karta: zaznaczasz, co wdrożyć (punkty sporne są domyślnie
  odznaczone), możesz dopisać uwagi, potem „Wdróż zaznaczone” albo „Nie wdrażaj”. Modele czekają, ile
  trzeba; wybór przetrwa zamknięcie programu.
- Wdrażający dostaje tylko wybrane punkty, a sprawdzający oceniają zgodność z Twoim wyborem.
- Menu Debata: „Najpierw podsumowanie: sam wybierasz, co wdrożyć” (domyślnie włączone; wyłączone daje
  dawne automatyczne wdrożenie).

## 1.0.16 — 2026-11-09
- Na górnym pasku widać, kto teraz pracuje: świecąca pigułka w kolorze modelu z czasem pracy i bieżącą
  czynnością (np. „Edit: ui/index.html”), a pod paskiem przesuwa się smuga światła. Kliknięcie przewija
  do odpowiedzi. Przy kilku modelach naraz pigułki są krótsze, czynność jest w dymku.
- Statystyki obejmują też czas przed wersją 1.0.15: przy pierwszym otwarciu dołączana jest historia
  do 90 dni wstecz z dzienników sesji Claude/Haiku i Codexa (tylko uruchomienia z TrybunAI w tym
  folderze, bez rozmów prowadzonych poza nim). Antigravity takich danych nie zapisuje.
- Nowy zrzut ekranu w README.

## 1.0.15 — 2026-11-08
- Statystyki (przycisk na górze): zużycie tokenów w czasie na wykresie słupkowym z podziałem na modele,
  za 24 godziny (co godzinę), 7, 30 albo 90 dni (co dzień). Do wyboru: nowe wejście + wyjście, wszystko
  z odczytem z cache albo samo wyjście. Po najechaniu na słupek: wartości dla każdego modelu; pod wykresem
  tabela z sumami.
- Każde uruchomienie modelu (czat, debata, wdrożenie, sprawdzanie, Prompter, pamięć) zapisuje swoje
  tokeny do `.trybunai/tokeny.jsonl`, który przetrwa „Nową rozmowę”. Liczby z Claude/Haiku, Codexa,
  Antigravity i Gemini.

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
