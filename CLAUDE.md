# TrybunAI — zasady dla modeli pracujących nad tym kodem

## Numer wersji (obowiązkowe)

Wersja jest w jednym miejscu: `trybun/__init__.py` (`__version__ = "MAJOR.MINOR.PATCH"`).

- **PATCH** (trzecia liczba): zwiększ o 1 przy **każdej** zmianie w kodzie
  (`*.py`, `ui/`, `build.ps1`, zasoby wbudowywane w exe). Jedna paczka zmian
  w jednej odpowiedzi = jedno podbicie, nie podbijaj kilka razy w tej samej odpowiedzi.
  Same zmiany w dokumentacji (`*.md`) nie zmieniają wersji.
- **MAJOR.MINOR** (dwie pierwsze liczby): zmieniaj **tylko wtedy, gdy właściciel
  wprost o to poprosi** (np. „wydajemy 1.1”). Wtedy PATCH wraca do 0.
- Po podbiciu dopisz wpis na górze `CHANGELOG.md`: wersja, data, krótko co się zmieniło.
- W odpowiedzi podaj nową wersję, np. „Wersja: 1.0.4”.

Przykład: 1.0.3 → poprawka → 1.0.4 → kolejna → 1.0.5 → „zrób 1.1” → 1.1.0.

## Budowanie i testy

- Testy: `.venv\Scripts\python.exe -m unittest discover -s tests`
- Exe: `.\build.ps1` (uruchamia testy, potem PyInstaller → `dist\TrybunAI.exe`).
