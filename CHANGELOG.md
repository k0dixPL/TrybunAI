# Zmiany

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
