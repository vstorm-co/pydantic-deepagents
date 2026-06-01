# Raport: kierunki rozwoju CLI (`apps/cli`)

> Analiza stanu obecnego + roadmapa pod kątem **wyglądu i "demo value"** (co widać i co da się pokazać).
> Data: 2026-06-01. Bazuje na pełnym przeglądzie kodu (68 plików, ~14,3k linii).

---

## ✅ Status implementacji (2026-06-01)

Sprint 1 + część Sprint 2 zaimplementowane (wszystko w `apps/cli`, 2328 testów zielonych, 100% coverage `pydantic_deep`):

| Zadanie | Status | Gdzie |
|---|---|---|
| #5 Prawdziwe diffy `+/-` + badge `+N -M` | ✅ | `widgets/tool_call.py` (`_diff_lines`, `_build_preview`) |
| #5b `write_file` pokazuje `-` przy nadpisaniu | ✅ | `chat._capture_old_content` (race-free: event przed wykonaniem) + widget diff |
| #2 Pełne komendy (koniec ucięcia do 60) | ✅ | `widgets/tool_call.py` (`execute` → `$ …` + output) |
| #6 Sidebar: idle agenci zostają (dim) | ✅ | `screens/chat.py` (`_known_subagents`, `_update_subagents_panel`) |
| #4 Feedback anulowania `⏹ stopping…` | ✅ | `tool_call.mark_cancelling`, `app._signal_cancelling` |
| #3 Approval „(1 of N)" przy wielu callach | ✅ | `modals/approval.py`, pętla w `chat.py` |
| #1 Wklejanie obrazków (`/paste` + Ctrl+V + `@img.png`) | ✅ | `clipboard_image.py`, `chat.py`; Ctrl+V przez `PromptInput.on_key` → `PasteImageRequested` (focused Input zjadał app-binding) |
| A4 Ikony narzędzi | ✅ | `widgets/tool_call.py` (`_TOOL_ICONS`) |
| A9 Podsumowanie tury | ✅ | `chat.py` (`_format_turn_summary`) |
| A10 Eksport `/screenshot` (SVG) | ✅ | `commands.py` |

Nowe testy: `tests/test_cli_clipboard_image.py`, `tests/test_cli_tool_call_widget.py`, `tests/test_cli_image_paste.py`, `tests/test_cli_new_features.py`.

**Pozostaje (świadomie, większy zakres):** A1 syntax-highlighting outputów, A6 file-tree w sidebarze, oraz flagowe z sekcji C (C11 accept/reject per hunk, C13 graf forków). Diagnoza i lokalizacje poniżej pozostają aktualne jako spec.

> Uwaga do #4: mechanika anulowania (kill drzewa procesów) działa już poprawnie dla `LocalBackend` — pydantic-ai 1.102 robi `cancel_and_drain` wszystkich równoległych tasków, a backend `killpg` na grupie procesów. Brakowało głównie **natychmiastowego feedbacku wizualnego** (dodany). Pozostały realny limit dotyczy backendów z synchronicznym `execute` w wątku (np. część sandboxów), gdzie wątku nie da się przerwać — to ograniczenie backendu, poza zakresem `apps/cli`.

---

## 1. TL;DR

Aplikacja jest pod maską bardzo bogata (forking/branching, sesje, skills, memory, subagenci, teams, reminders, improve-flow, cost tracking, sandbox). **Problem nie leży w braku funkcji, tylko w warstwie prezentacji** — to, co najmocniej sprzedaje produkt na demie i w marketingu, jest najsłabiej dopracowane:

- nie widać pełnych komend i pełnych diffów,
- brak wklejania obrazków,
- równoległe tool-calle i anulowanie wyglądają na zepsute (a częściowo są),
- sidebar "gubi" elementy zamiast je wyszarzać.

Te rzeczy psują pierwsze wrażenie bardziej niż brak jakiejkolwiek zaawansowanej funkcji. **Rekomendacja: najbliższy sprint = polish warstwy wizualnej tool-calls + input, dopiero potem nowe duże funkcje.**

---

## 2. Twoje uwagi — diagnoza + miejsce w kodzie + fix

### 🖼️ #1 — Brak wklejania obrazków ze schowka (clipboard)

**Stan:** funkcji nie ma w ogóle. Input obsługuje tylko tekst i referencje `@plik` (tekstowe, czytane jako string — `screens/chat.py:669` `_expand_file_refs`). Schowek używany jest tylko w jedną stronę: `/copy`, `/copy-all`.

**Dobra wiadomość:** pydantic-ai w pełni wspiera multimodal — `BinaryContent(data, media_type)` + `UserPromptPart.content` przyjmuje `Sequence[UserContent]`. Backend jest gotowy, CLI po prostu zawsze wysyła sam `str`.

**Co trzeba dodać:**
| Plik | Co |
|------|-----|
| `widgets/input_area.py` (`PromptInput`, ~96-163) | handler wklejania + skrót (Cmd/Ctrl+V), detekcja obrazka w schowku |
| (nowy) clipboard reader | macOS: `PIL.ImageGrab.grabclipboard()` lub `pngpaste`; cross-platform fallback |
| `messages.py` | nowy event `ImagePasted(data, media_type)` |
| `screens/chat.py` (`on_user_submitted`, `_run_agent` ~561-698) | budowa listy `[text, BinaryContent(...)]` zamiast samego stringa |
| `widgets/user_message.py` | render miniatury/placeholdera `[🖼 PNG 1024×768]` |

**Demo value: 🔥🔥🔥 najwyższy.** "Wklejam screenshot błędu i agent od razu go widzi" to klasyczny killer-shot na demie (dokładnie to robi Claude Code / Cursor). Warto zacząć od placeholdera tekstowego `[image]`, a render miniatur (sixel/iTerm protocol) dorzucić później.

---

### 📏 #2 — Nie widać całych komend

**Przyczyna:** twarde ucięcie do 60 znaków w nagłówku tool-calla.
`widgets/tool_call.py:45`:
```python
elif tool_name == "execute":
    cmd = args.get("command", "?")
    return str(cmd)[:60]        # ← ucięcie
```
Co gorsza: **rozwinięcie tool-calla pokazuje tylko output komendy, nigdzie nie ma pełnej komendy.** Pełny string siedzi w `self.args["command"]`, ale nigdy nie jest renderowany.

**Fix:** w `_build_preview()` dodać gałąź dla `execute`, która w stanie rozwiniętym pokazuje pełną komendę (np. `$ <cmd>` na górze, pod spodem output). Krótki ticket, duży efekt wizualny.

**Demo value: 🔥🔥** — bez tego nie da się pokazać "co agent właściwie odpalił".

---

### 🧬 #3 — "Jedna zatwierdzona komenda, a odpaliły się dwie"

**To nie halucynacja — to równoległe wykonanie tool-calls (by design w pydantic-ai).**
Domyślny tryb to `parallel` (`tool_manager.py`, `_parallel_execution_mode_ctx_var default='parallel'`). Flow approvali (`screens/chat.py:971-994`) zbiera zgody **pojedynczo, modal po modalu**, ale potem wszystkie zatwierdzone calle lecą do `agent.iter(...)` i w `_call_tools` startują jako równoległe `asyncio.create_task(...)` naraz.

Czyli: model wygenerował 2 tool-calle, Ty zatwierdziłeś (być może jeden modal po drugim, co wyglądało jak "jedno potwierdzenie"), a wykonały się oba równolegle.

**To, co psuje UX, to brak czytelnej prezentacji:** nie widać, że to były 2 osobne calle uruchomione jednocześnie.

**Fix (do wyboru / łącznie):**
1. **Wizualnie:** grupować równoległe calle w jeden blok "Running 2 commands in parallel" z osobnymi wierszami statusów — wtedy zachowanie staje się czytelne, nie "dziwne".
2. **Zachowaniowo:** dla narzędzi wymagających approvala wymusić tryb `sequential`, albo pokazać JEDEN zbiorczy modal "Approve 2 tool calls" z listą, zamiast modali łańcuchowo.

**Demo value: 🔥🔥** — równoległość to atut (szybsze), ale tylko jeśli widać go jako feature, a nie glitch.

---

### ⛔ #4 — ESC anuluje jeden call, drugi leci dalej i nie da się go zatrzymać

**Najpoważniejszy bug z całej listy.** ESC (`app.py:512-513`) robi `self.agent_task.cancel()` — anuluje główny task asyncio. Ale przy równoległych tool-callach:
- `_call_tools` używa `asyncio.wait(pending, return_when=FIRST_COMPLETED)`,
- gdy jeden task się kończy i jego event jest wyemitowany, anulowanie głównego tasku **nie gwarantuje** terminacji pozostałych, wciąż działających subprocessów.

Backend *ma* poprawny kill drzewa procesów (`local.py`: `start_new_session=True` + `_kill_proc_tree(proc)` w `except CancelledError`), ale przy parallel jest **race**: nie wszystkie taski narzędzi są deterministycznie cancelowane i awaitowane przy przerwaniu.

**Fix:** w handlerze przerwania (lub w pętli `_call_tools`) jawnie zebrać *wszystkie* in-flight task narzędzi, zrobić `.cancel()` na każdym i `await asyncio.gather(*tasks, return_exceptions=True)` zanim wyjdziemy — żeby propagacja `CancelledError` dotarła do każdego subprocessu. Plus: wizualny stan "Cancelling…" dla każdego wiersza, dopóki kill się nie potwierdzi.

**Demo value:** to nie feature, to **wiarygodność**. Agent, którego nie da się zatrzymać, jest groźny — to blocker zaufania. **Priorytet: najwyższy z bugów.**

---

### ➕➖ #5 — Brak diffów +/- przy edycji plików

**Częściowo jest, ale słabo:**
- `edit_file` (`tool_call.py:204-223`) renderuje diff, ale tylko **pierwsze 3 linie** old/new, bez kontekstu, bez numerów linii, tylko w preview.
- `write_file` (`tool_call.py:226-230`) **nie ma diffa w ogóle** — tylko `"wrote N lines to <path>"`.
- `modals/diff_view.py` / `diff_picker.py` służą wyłącznie do `/diff` (git) i fork-diff, **nie są podpięte pod tool-calle**.

**Fix:** prawdziwy unified diff przez `difflib.unified_diff` + kolorowanie (Rich `Syntax`/markup), z numerami linii i kontekstem; dla `write_file` przy nadpisaniu istniejącego pliku liczyć diff względem starej zawartości (backend ma read). Limit rozwijalny ("… 12 more lines").

**Demo value: 🔥🔥🔥** — diff +/- to *wizualna esencja* asystenta kodu. Najmocniejszy screenshot marketingowy zaraz po wklejaniu obrazków.

---

### 🎛️ #6 — Subagenci: nieaktywni znikają z sidebara zamiast się wyszarzać

**Przyczyna:** lista jest **przebudowywana od zera** z samych aktywnych tasków.
`screens/chat.py:1318-1321`:
```python
agents_list: list[dict[str, Any]] = []
for info in subagent_tasks.values():     # tylko aktualnie działające
    agents_list.append(info)
...
sa_widget.agents = agents_list           # idle agenci z _init_side_panel znikają
```
Domyślni "idle" agenci ustawieni przy starcie (`_init_side_panel`, ~`:264`) nie są nigdy mergowani z powrotem — przy pierwszym tasku znikają. Sam widget (`subagents_panel.py:31-69`) *umie* stylować statusy (zielony/żółty/dim), ale dostaje już okrojoną listę.

**Fix:** trzymać trwałą listę "znanych" subagentów i **mergować** w nią status aktywnych, zamiast podmieniać. Nieaktywni → render `dim`. Drobna zmiana, duży efekt "żywego panelu".

**Demo value: 🔥** — stabilny, "oddychający" panel boczny wygląda dużo bardziej pro niż migający.

---

## 3. Tabela priorytetów (Twoje uwagi)

| # | Problem | Typ | Wysiłek | Demo value | Priorytet |
|---|---------|-----|---------|------------|-----------|
| #4 | ESC nie zabija wszystkich callów | **Bug krytyczny** | M | zaufanie | **P0** |
| #5 | Brak prawdziwych diffów +/- | UX/wizual | M | 🔥🔥🔥 | **P0** |
| #1 | Wklejanie obrazków | Feature | M-L | 🔥🔥🔥 | **P0** |
| #2 | Ucięte komendy | UX/wizual | S | 🔥🔥 | **P1** |
| #6 | Znikający sidebar | Bug wizualny | S | 🔥 | **P1** |
| #3 | Parallel calls wyglądają dziwnie | UX/wizual | S-M | 🔥🔥 | **P1** |

S = <0.5 dnia, M = ~1 dzień, L = kilka dni. Wszystkie zmiany mieszczą się w `apps/cli` (zgodne z zasadą: bez modyfikacji zewn. libów).

---

## 4. Czego brakuje poza Twoją listą (pod kątem "co widać")

Posortowane wg stosunku **demo-value / koszt**.

### A. Quick wins wizualne (S, duży efekt)
1. **Syntax highlighting wyników** `read_file`/`write_file` (Rich `Syntax`, detekcja po rozszerzeniu) — teraz wszystko jest płaskim tekstem.
2. **Streaming "typing" + thinking display** — pokaż reasoning ("💭 Thinking…") i płynne dopisywanie tokenów. *(masz to już w memory jako brak: `project_tui_improvements`).*
3. **Live token counter** w trakcie streamu (nie tylko po) — *(też w `project_tui_improvements`).*
4. **Ikony narzędzi** (📖 read, ✏️ edit, ⚡ bash, 🔍 grep) + kolor-kodowane statusy — natychmiastowa czytelność.
5. **Sticky "Running…" footer** z aktualnym narzędziem i czasem — widać, że "żyje".

### B. Średnie, mocne na demo (M)
6. **Tree-view / file explorer w sidebarze** — pokazuje "agent pracuje na realnym repo".
7. **Inline "Applied edit" z liczbą +N/-M** w nagłówku edycji pliku (jak GitHub) — bardzo czytelny sygnał zmian.
8. **Skróty `@file` z podglądem** + `#linia` referencje.
9. **Toast/summary po turze**: "✓ 3 pliki zmienione, 2 komendy, $0.04, 12s" — świetny "money shot".
10. **`/screenshot` lub eksport sesji do SVG/HTML** (Textual `export_text`/`save_screenshot`) — gotowe assety marketingowe prosto z aplikacji.

### C. Większe kierunki (L) — wybrać 1-2 jako "flagowe"
11. **Diff z akcją accept/reject per hunk** — interaktywne zatwierdzanie zmian (to, czego brakuje wg gap-analizy). Bardzo "produktowe".
12. **Integracja GitHub PR** (`gh` CLI): twórz/review PR z poziomu TUI.
13. **Wizualizacja forków jako drzewo/graf** — masz potężny system forking, ale pokazany płasko; graf równoległych gałęzi z kosztem/statusem to unikalny wyróżnik (nikt z konkurencji tego nie ma tak ładnie).
14. **Asciinema/agent-replay** — odtwarzanie sesji jako "film", idealne na landing page.

---

## 5. Rekomendowana kolejność (2 sprinty)

**Sprint 1 — "Trust & Polish" (wszystko w `tool_call.py`, `chat.py`, `input_area.py`):**
1. #4 fix anulowania (P0, bezpieczeństwo/zaufanie)
2. #5 prawdziwe diffy +/- (P0, najlepszy screenshot)
3. #2 pełne komendy + #6 sidebar merge + #3 grupowanie parallel (P1, szybkie)
4. A1-A4 quick winy wizualne

**Sprint 2 — "Wow features":**
5. #1 wklejanie obrazków (killer demo)
6. A9 podsumowanie tury + A10 eksport screenshotów (assety marketingowe)
7. Wybrać 1 flagę z C: rekomendacja → **C13 wizualizacja forków** (unikalny wyróżnik) lub **C11 accept/reject diffów** (najbardziej "produktowe").

---

## 6. Najmocniejszy przekaz marketingowy (gdy powyższe gotowe)

> "Wklej screenshot, zobacz dokładnie co agent zmienia (diff +/-), odpalaj komendy równolegle i zatrzymaj wszystko jednym ESC — a gdy chcesz pewności, rozszczep zadanie na kilka gałęzi i wybierz najlepszą."

To zdanie obecnie *nie jest prawdziwe* w 4 z 5 punktów. Po Sprincie 1+2 — będzie. I każdy z tych punktów to osobny, atrakcyjny GIF/screenshot.
