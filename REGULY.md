# Wspólne zasady dla modeli (TrybunAI)

Ten plik jest jedynym źródłem wspólnych zasad. `CLAUDE.md`, `AGENTS.md` i `GEMINI.md` na niego wskazują.

## Numer wersji (obowiązkowe)

Wersja jest w jednym miejscu: `trybun/__init__.py` (`__version__ = "MAJOR.MINOR.PATCH"`).

- **PATCH** (trzecia liczba): zwiększ o 1 **tylko w momencie wypchnięcia na git**, jednym podbiciem
  na wypchnięcie (razem z wpisem w `CHANGELOG.md` i tagiem). Dopóki zmiany powstają lokalnie
  i nie są wypchnięte, numer zostaje bez zmian, nawet gdy zmienia się kod
  (`*.py`, `ui/`, `build.ps1`, zasoby wbudowywane w exe).
  Same zmiany w dokumentacji (`*.md`) nie zmieniają wersji.
- **MAJOR.MINOR** (dwie pierwsze liczby): zmieniaj **tylko wtedy, gdy właściciel
  wprost o to poprosi** (np. „wydajemy 1.1”). Wtedy PATCH wraca do 0.
- Przy podbiciu dopisz wpis na górze `CHANGELOG.md`: wersja, data, krótko co się zmieniło
  od ostatniego wypchnięcia.
- W odpowiedzi podawaj aktualny numer; „nowa wersja” tylko przy wypchnięciu.

Przykład: 1.0.3 → kilka lokalnych poprawek (nadal 1.0.3) → wypchnięcie → 1.0.4 → „zrób 1.1” → 1.1.0.

## Budowanie i testy

- Testy: `.venv\Scripts\python.exe -m unittest discover -s tests`
- Exe: `.\build.ps1` (uruchamia testy, potem PyInstaller → `dist\TrybunAI.exe`).

## Oszczędzanie tokenów

- Zacznij od `.trybunai/mapa/INDEX.md`, potem notatka modułu. Kod czytaj wybiórczo.
- Duże pliki (np. `ui/index.html`) przeszukuj (grep), a czytaj fragmentami (offset/limit).
- Nie czytaj ponownie plików, których zawartość już widziałeś w tej rozmowie,
  chyba że dziennik TrybunAI zgłasza ich zmianę.
- Długie wyniki poleceń ucinaj (`tail`, `head`, limit wyników), testy uruchamiaj z krótkim wynikiem.
- Nie tworzysz plików pomocniczych ani raportów, o które nikt nie prosił.
- Trwałe ustalenia zapisuj w pamięci projektu, nie tutaj.

## Czego tu nie wpisywać

- Opisu architektury (jest w mapie) ani historii zmian (jest w `CHANGELOG.md` i w git).
