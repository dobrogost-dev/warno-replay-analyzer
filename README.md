# WARNO Replay Analyzer

Jeden plik `.exe`. Uruchamiasz — sam znajduje Twoje repleje, analizuje wszystkie,
buduje raport HTML i otwiera go w przeglądarce. Bez instalacji, bez Pythona,
bez serwera, bez internetu.

```
dist\WARNO Replay Analyzer.exe
```

## Co robi

1. **Znajduje repleje** w dwóch miejscach:
   * Steam Cloud — `<Steam>\userdata\<konto>\1611600\remote` (tu leży całe
     archiwum; biblioteki Steam są czytane z rejestru i `libraryfolders.vdf`),
   * `%USERPROFILE%\Saved Games\EugenSystems\WARNO` oraz
     `Documents\EugenSystems\WARNO` i OneDrive (tu zwykle trafiają repleje
     przemianowane albo przysłane przez kogoś).

   Ten sam replej leżący w obu miejscach jest liczony raz. Możesz też przeciągnąć
   folder na `.exe` albo podać ścieżkę w wierszu poleceń.
2. **Czyta każdy `.rpl3`** — nagłówek JSON w kontenerze ESAV: mapa, tryb, wersja
   gry, ustawienia lobby, wszyscy gracze (nick, Eugen ID, ELO, poziom, drużyna)
   i blok wyniku na końcu pliku. Repleje przerwane (bez bloku wyniku) są
   oznaczane, nie pomijane.
3. **Dekoduje talie** z `PlayerDeckContent` — dywizja, wszystkie karty,
   weterancja i transport każdej z nich.
4. **Podstawia prawdziwe nazwy** dywizji i jednostek, czytając je z Twojej
   instalacji WARNO (patrz niżej).
5. **Zapisuje `WARNO Replay Report.html`** obok `.exe` i otwiera go w przeglądarce.
   Cały raport — dane, style, skrypt — jest w tym jednym pliku, więc można go
   wysłać komuś mailem i otworzy się u niego tak samo.

## Skąd biorą się nazwy jednostek

Liczby w kodzie talii to indeksy z tabeli serializatora gry. Eugen dostarcza ją
otwartym tekstem w paczce moddingowej, więc analizator czyta ją wprost z Twojej
instalacji:

| Plik w instalacji WARNO | Co z niego bierzemy |
| --- | --- |
| `Mods/ModData/base.zip` → `Decks/DeckSerializer.ndf` | ID dywizji i jednostek używane w kodach talii |
| `Mods/ModData/base.zip` → `Decks/Divisions.ndf` | koalicja, kraj, typ, token nazwy dywizji |
| `Mods/ModData/base.zip` → `Gfx/UniteDescriptor.ndf` | token nazwy, kategoria (LOG/INF/ART/TNK/REC/AA/HEL/AIR), kraj |
| `Mods/ExampleAssets/Localisation/UNITS.csv` | token → angielska nazwa |

Dzięki temu nazwy zawsze pasują do **Twojej** wersji gry, także po patchu.
Instalacja Steam jest wykrywana automatycznie (rejestr + `libraryfolders.vdf`);
wynik jest cache'owany w `%LOCALAPPDATA%\WARNO Replay Analyzer\`.

Jeśli gry nie ma na tym komputerze, używany jest snapshot zaszyty w `.exe`
(384 dywizje, 2839 jednostek). Nieznane ID pokazują się jako `#1234`.

## Raport

**Zakładka Matches** — tabela wszystkich meczów z sortowaniem po każdej kolumnie.
Kliknięcie wiersza rozwija szczegóły: obie drużyny, gracze z ELO i poziomem,
a pod każdym graczem pełna talia pogrupowana jak w armory, z weterancją
(▲/▲▲/▲▲▲), transportami i przyciskiem kopiowania kodu talii do gry.

Filtry po lewej: perspektywa (czyj wynik liczymy), szukanie gracza, konkretne
zestawienie graczy A vs B, typ meczu, wynik, minimalny czas, dywizje A vs B,
mapa, rozmiar, zakres dat. Strony A/B są zamienne — nie musisz zgadywać, po
której stronie ktoś grał.

**Zakładka gracza** (przycisk „Report" przy graczu lub w panelu filtrów) —
statystyki liczone na aktualnie przefiltrowanej bazie: winrate, bilans, mediana
czasu, wykres ELO w czasie, oraz winrate wg własnej dywizji, przeciw dywizji
wroga, wg mapy, z sojusznikiem, przeciw graczowi i najczęściej brane jednostki.

Perspektywa („kim jesteś") jest ustalana po koncie Steam zalogowanym na tym
komputerze, a gdy się nie da — po tym, kto zapisał najwięcej replejów. Możesz ją
zmienić w panelu filtrów.

## Wiersz poleceń

```
WARNO Replay Analyzer.exe [FOLDER ...] [opcje]

  -o, --out KATALOG   gdzie zapisać raport (domyślnie obok .exe)
  --json              zapisz też data.json
  --no-open           nie otwieraj przeglądarki
  --game-dir ŚCIEŻKA  folder instalacji WARNO, jeśli nie został wykryty
  --refresh-data      wczytaj nazwy z gry ponownie, z pominięciem cache
```

Bez argumentów (np. po dwukliku) skanuje domyślny folder replejów i czeka na
Enter przed zamknięciem okna.

## Budowanie ze źródeł

```
pip install pyinstaller
python tools/make_snapshot.py     # odświeża snapshot nazw (wymaga WARNO)
python build.py                   # -> dist/WARNO Replay Analyzer.exe
```

Można też uruchamiać bez budowania: `python src/main.py`.

## Struktura

```
src/main.py            wejście: wykrywanie folderów, przebieg, zapis, przeglądarka
src/replay.py          parser .rpl3 i dekoder kodów talii
src/gamedata.py        wyciąganie nazw z instalacji gry + cache + fallback
src/report.py          wklejanie CSS/JS/danych w jeden plik HTML
src/assets/            viewer.html / viewer.css / viewer.js + snapshot nazw
tools/make_snapshot.py generator snapshotu dołączanego do .exe
build.py               budowanie .exe
reference/             materiał wyjściowy (prototyp w Pythonie + makieta UI)
```

## Uwagi o formacie repleja

* Kontener `ESAV`; nagłówek JSON zaczyna się od `{"game"` ok. 48 bajtu.
* `ingamePlayerId` to indeks w liście graczy posortowanej po numerze slotu —
  wynik (`Victory` 0–6) jest zapisany względem tego gracza.
* Blok `{"result":...}` na końcu pliku **nie istnieje**, gdy mecz przerwano.
* W kodzie talii ID dywizji to wartość wprost z `DeckSerializer`, a ID jednostki
  i transportu to ta wartość **+1** (0 jest zarezerwowane dla „brak transportu").
* `PlayerElo` równe 0 oznacza brak rankingu, nie wynik 0 — nie jest uśredniane.
* Nazwa mapy potrafi kłamać o rozmiarze (2v2 bywa grane na mapie `_1vs1_`),
  więc rozmiar meczu liczony jest z faktycznego składu drużyn.
