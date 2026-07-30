# WARNO Replay Analyzer

Jeden plik `.exe`. Uruchamiasz — sam znajduje Twoje repleje, analizuje wszystkie,
buduje raport HTML i otwiera go w przeglądarce. Bez instalacji, bez Pythona,
bez serwera, bez internetu.

## Pobieranie

Weź `WARNO Replay Analyzer.exe` z [zakładki Releases](https://github.com/dobrogost-dev/warno-replay-analyzer/releases/latest)
i po prostu go uruchom. Nic nie instaluje i nic nie zapisuje w katalogu gry —
raport ląduje obok `.exe`.

Windows pokaże ostrzeżenie SmartScreen („Windows protected your PC"), bo plik
nie jest podpisany certyfikatem. **Więcej informacji → Uruchom mimo to.**
Jeśli wolisz nie ufać cudzemu binarium, zbuduj je sam — patrz *Budowanie ze
źródeł* na dole.

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
   instalacji WARNO (patrz niżej), i dokłada **herby dywizji** wyciągnięte
   wprost z plików gry.
5. **Zapisuje `WARNO Replay Report.html`** obok `.exe` i otwiera go w Twojej
   domyślnej przeglądarce — tej z ustawień Windows, odczytanej z `UserChoice`
   w rejestrze. (Standardowe `webbrowser.open()` wysyła URL `file:///`, a ten
   protokół jest w Windows zwykle przejęty przez Edge; `os.startfile` idzie za
   skojarzeniem `.html`, które maszynowy ProgId `htmlfile` też potrafi przekierować
   na Edge. Stąd jawny odczyt wyboru użytkownika.)
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

## Herby dywizji

Herbów nie ma w paczce moddingowej — są „ugotowane" w spakowanych archiwach gry,
więc wyciąga je osobne narzędzie budowania, a `.exe` wozi gotowe PNG-i
(114 herbów, ~760 KB).

```
pip install zstandard
python tools/extract_emblems.py        # -> src/assets/emblems.json
```

Łańcuch: `Divisions.ndf` daje każdej dywizji `EmblemTexture`, `DivisionTextures.ndf`
tłumaczy to na ścieżkę assetu, a archiwa `Data/PC/**/ZZ_*.dat` trzymają go jako
`.tgv`. Format kontenera i tekstury odtworzony za
[ev1313/wgrd-cons-parsers](https://github.com/ev1313/wgrd-cons-parsers), z dwiema
różnicami, które WARNO ma względem Wargame: nagłówek słownika plików ma 9 bajtów
zamiast 10, a mipmapy siedzą w ramkach **Zstandard** za krótkim nagłówkiem `ZSTD`.
Piksele to `A8B8G8R8_LIN`, czyli zwykłe RGBA — nie ma bloków BC do dekodowania.
Czytnik ([tools/warno_edat.py](tools/warno_edat.py)) sprawdza sumy MD5 każdego
rozpakowanego pliku. Archiwa są przeglądane od najstarszej wersji do najnowszej,
więc łatki nadpisują herby z wersji bazowej.

Po patchu, który dodaje dywizje, wystarczy uruchomić narzędzie ponownie.

## Raport

**Zakładka Matches** — tabela wszystkich meczów z sortowaniem po każdej kolumnie.
Kliknięcie wiersza rozwija szczegóły: obie drużyny, gracze z ELO i poziomem,
a pod każdym graczem pełna talia pogrupowana jak w armory, z weterancją
(▲/▲▲/▲▲▲), transportami i przyciskiem kopiowania kodu talii do gry.

Filtry po lewej: perspektywa (czyj wynik liczymy), szukanie gracza, konkretne
zestawienie graczy A vs B, typ meczu, wynik, minimalny czas, **ELO przeciwnika**,
dywizje A vs B, mapa, rozmiar, zakres dat. Strony A/B są zamienne — nie musisz
zgadywać, po której stronie ktoś grał.

Suwak ELO przeciwnika działa **wyłącznie na meczach rankingowych** — pozostałe
typy przechodzą przez niego nietknięte, bo poza ladderem ELO przeciwnika nic nie
znaczy. Chcesz zobaczyć same rankingowe? Odznacz „Casual multiplayer".

**Zakładka gracza** (przycisk „Full report" u góry filtrów, albo „Report" przy
dowolnym graczu) — statystyki liczone na aktualnie przefiltrowanej bazie:
winrate, bilans, mediana czasu, wykres ELO w czasie, oraz winrate wg własnej
dywizji, przeciw dywizji wroga, wg mapy, z sojusznikiem i przeciw graczowi.

Te pięć tabel jest **kompletnych** — nic nie jest ucinane, długie listy przewijają
się w swoim polu, a podtytuł podaje liczbę wierszy. Każdą kolumnę można sortować
(nazwa, GAMES, W–L, WR), niezależnie w każdej tabeli. Wyjątkiem jest lista
najczęściej branych jednostek: tam pokazywane jest 25 pozycji z kilkuset.

Perspektywa („kim jesteś") jest ustalana po koncie Steam zalogowanym na tym
komputerze, a gdy się nie da — po tym, kto zapisał najwięcej replejów. Możesz ją
zmienić w panelu filtrów.

## Awatary Steam

Awatary graczy pobierane są **domyślnie** — to jedyny krok korzystający z sieci.
Wyłącza je `--no-avatars`.

Repleje zawierają SteamID64 każdego gracza (w polu `PlayerAvatar`), a publiczny
XML profilu Steam zwraca adres miniatury bez żadnego klucza API. Na zewnątrz
wychodzą wyłącznie te SteamID — nic o Tobie ani o Twoich meczach. Pobrane
miniatury (32×32, ~1 KB) lądują w `%LOCALAPPDATA%\WARNO Replay Analyzer\avatars`,
więc płacisz za to raz: pierwsze pobranie 433 awatarów zajęło minutę, każde
kolejne uruchomienie 2 sekundy. Nierozwiązane profile (usunięte, prywatne) są
zapamiętywane, żeby nie próbować ich w kółko.

Bez internetu jedno szybkie sprawdzenie ucina próbę i program leci dalej — nie
czeka na kilkaset timeoutów. Awatary powiększają raport o mniej więcej 600 KB.

Uwaga przy wysyłaniu raportu komuś: razem z nickami i Eugen ID pójdą też zdjęcia
profilowe wszystkich graczy. `--no-avatars` daje raport bez nich.

## Wiersz poleceń

```
WARNO Replay Analyzer.exe [FOLDER ...] [opcje]

  -o, --out KATALOG   gdzie zapisać raport (domyślnie obok .exe)
  --json              zapisz też data.json
  --no-open           nie otwieraj przeglądarki
  --no-avatars        nie pobieraj awatarów Steam (jedyny krok używający sieci)
  --refresh-avatars   pobierz awatary ponownie, z pominięciem cache
  --game-dir ŚCIEŻKA  folder instalacji WARNO, jeśli nie został wykryty
  --refresh-data      wczytaj nazwy z gry ponownie, z pominięciem cache
```

Bez argumentów (np. po dwukliku) skanuje domyślny folder replejów i czeka na
Enter przed zamknięciem okna.

## Budowanie ze źródeł

```
pip install pyinstaller zstandard
python tools/make_snapshot.py     # odświeża snapshot nazw (wymaga WARNO)
python tools/extract_emblems.py   # odświeża herby (wymaga WARNO)
python build.py                   # -> dist/WARNO Replay Analyzer.exe
```

`zstandard` jest potrzebny wyłącznie przy wyciąganiu herbów — samo `.exe` nie ma
żadnych zależności poza biblioteką standardową.

Można też uruchamiać bez budowania: `python src/main.py`.

Oba narzędzia wymagają zainstalowanego WARNO, ale ich wyniki są w repo, więc
samo `python build.py` wystarczy, żeby dostać działający `.exe` na maszynie bez
gry. Tak właśnie buduje go CI.

## Wydawanie nowej wersji

```
git tag v1.2
git push origin v1.2
```

[Workflow](.github/workflows/release.yml) buduje `.exe` na Windows, robi test
dymny na pustym katalogu i wystawia gotowy plik w Releases.

## Licencja i prawa

Kod na [MIT](LICENSE). Nazwy jednostek, dywizji i herby pochodzą z plików gry
i należą do Eugen Systems — są tu dołączone tylko po to, żeby narzędzie
podpisywało repleje także na komputerze bez zainstalowanego WARNO. Projekt nie
jest powiązany z Eugen Systems ani przez nich firmowany.

## Struktura

```
src/main.py            wejście: wykrywanie folderów, przebieg, zapis, przeglądarka
src/replay.py          parser .rpl3 i dekoder kodów talii
src/gamedata.py        wyciąganie nazw z instalacji gry + cache + fallback
src/avatars.py         opcjonalne pobieranie awatarów Steam + cache
src/report.py          wklejanie CSS/JS/danych w jeden plik HTML
src/assets/            viewer.html / viewer.css / viewer.js + snapshot nazw + herby
tools/make_snapshot.py generator snapshotu nazw dołączanego do .exe
tools/warno_edat.py    czytnik archiwów edat i tekstur TGV (tylko przy budowaniu)
tools/extract_emblems.py wyciąganie herbów dywizji z plików gry
build.py               budowanie .exe
reference/             materiał wyjściowy (prototyp w Pythonie + makieta UI)
```

## Uwagi o formacie repleja

* Kontener `ESAV`; nagłówek JSON zaczyna się od `{"game"` ok. 48 bajtu.
* Blok `{"result":...}` na końcu pliku **nie istnieje**, gdy mecz przerwano.
* `Victory` (0–6: 0/1/2 porażka totalna/duża/mała, 3 remis, 4/5/6 zwycięstwo
  małe/duże/totalne) jest zapisane **z perspektywy gracza, który zapisał
  replej** — blok wyniku tworzy jego klient.
* **`ingamePlayerId` nie wskazuje tego gracza.** Wygląda, jakby miał, ale na
  805 własnych replejach z tego komputera trafia tylko w 63% przypadków, a przy
  czterech graczach w 27%. Opieranie na nim wyniku dawało błędnego zwycięzcę
  w 224 z 814 meczów. Właściciela ustalamy po SteamID: ścieżka Steam Cloud
  `userdata/<account id>/` koduje go wprost (`SteamID64 = 76561197960265728 +
  account id`), a `PlayerAvatar` każdego gracza zawiera jego SteamID64.
  Dla replejów przysłanych przez kogoś innego zostaje `ingamePlayerId` jako
  przybliżenie — takie mecze są w szczegółach oznaczone jako zgadywane.
* W kodzie talii ID dywizji to wartość wprost z `DeckSerializer`, a ID jednostki
  i transportu to ta wartość **+1** (0 jest zarezerwowane dla „brak transportu").
* `PlayerElo` równe 0 oznacza brak rankingu, nie wynik 0 — nie jest uśredniane.
* Nazwa mapy potrafi kłamać o rozmiarze (2v2 bywa grane na mapie `_1vs1_`),
  więc rozmiar meczu liczony jest z faktycznego składu drużyn.
* **Mapa z sufiksem `_DUEL` nie oznacza gry rankingowej** — customy chodzą na
  tych samych mapach. Ladder rozpoznajemy po `GameType`: kolejki matchmakingowe
  (1 i 2) praktycznie nie mają nazwy lobby (13 z 180 przypadków, wobec 426 z 610
  dla `GameType=0`) i to po nich zmienia się ELO. Stara reguła oparta na mapie
  oznaczała jako rankingowe 377 z 814 meczów; realnie jest ich 203.
