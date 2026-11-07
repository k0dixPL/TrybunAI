# Zmiany

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
