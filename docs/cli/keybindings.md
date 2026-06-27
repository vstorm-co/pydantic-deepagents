# Keys & input

The CLI is keyboard-first. Once you know a handful of shortcuts, you rarely touch the mouse — send, steer, search, scroll, and switch panels without leaving the prompt.

This page lists every real key binding and every input trigger, exactly as the app wires them.

## The one you need first

```text
Enter      send the prompt
Ctrl+J     toggle multiline input
↑ / ↓      walk your input history (when the prompt is empty)
Esc        interrupt the agent / cancel
```

That's enough to hold a full conversation. Everything below adds one capability at a time.

## All keyboard shortcuts

| Key | What it does |
| --- | --- |
| `Enter` | Send the message |
| `Ctrl+J` | Toggle multiline input (and send, while in multiline) |
| `↑` / `↓` | Step through input history — only on an empty prompt |
| `Ctrl+P` | Open the input-history picker (fuzzy-pick a past prompt) |
| `Ctrl+R` | Search messages in the conversation |
| `Ctrl+K` | Toggle the todos panel |
| `Ctrl+L` | Clear the screen |
| `Ctrl+V` | Paste an image from the clipboard |
| `Ctrl+Shift+C` | Copy the current mouse-drag selection |
| `Ctrl+C` | Interrupt the running agent — or exit if idle |
| `Esc` | Interrupt the agent / cancel a fork / clear attachments / refocus the prompt |
| `Ctrl+D` | Quit |
| `PgUp` / `PgDn` | Scroll the message view |
| `F1` | Open help |
| `F2` | Open settings |
| `F5` | Show context-window usage |

!!! note "Why `Ctrl+Shift+C` for copy?"
    `Ctrl+C` is reserved for interrupting the agent, so the usual copy action
    moves to `Ctrl+Shift+C`. Drag to select text, then `Ctrl+Shift+C`.

!!! tip "`Esc` does the right thing"
    `Esc` is context-aware. If the agent is running, it interrupts. If a fork is
    active, it aborts the branch. If you have pending image attachments, it
    clears them. Otherwise it just puts focus back on the prompt.

## Input triggers

Some characters do something special when you type them at the prompt. They never reach the model as text — they open a picker or change how the line is handled.

| Type this | What happens |
| --- | --- |
| `/` (first character) | Open the command picker |
| `@` (at a word boundary) | Open the file picker — inserts an `@path` reference |
| `!` (first character) | Run the rest of the line as a shell command (e.g. `!make test`) |
| `>>` (prefix) | Steer the running agent, or queue a follow-up while it's busy |

`@path` references are expanded into file contents when you submit, so `@README.md summarize this` sends the model the file plus your instruction. Paths with spaces are quoted automatically.

!!! info "`>>` while the agent is working"
    Type `>>do X instead` mid-run to steer the current turn. Plain text typed
    during a run is queued as a follow-up and sent on the next turn. A bare `!`
    shell command always runs immediately, busy or not.

## Multiline input

For anything longer than a line — a code block, a multi-paragraph spec — press `Ctrl+J` to switch the prompt into a multiline editor.

```text
Ctrl+J     send (submit the multiline buffer)
Esc        cancel multiline, back to single line
Enter      insert a newline
```

You don't have to toggle it yourself for pastes. When you paste text that contains newlines into the single-line prompt, the CLI **automatically** switches to multiline and preserves the structure — your code block stays intact.

!!! example "Check it"
    Copy a few lines of code and paste them at the prompt. The input grows into
    a multiline box with your text laid out exactly as copied — no mangled
    single line.

## Drag and drop files

Drag a file from your file manager onto the terminal and the CLI attaches it for you:

- **Images** (`.png`, `.jpg`, and friends) attach as an image chip on the next prompt — the same path `Ctrl+V` takes for clipboard screenshots.
- **Any other file** drops in as an `@path` reference, so its contents are expanded into the prompt when you send.

Either way you get a visible chip or reference, so you always know what's going along with your message. Press `Esc` on an empty prompt to clear pending attachments.

!!! tip "Screenshots, fast"
    On macOS, copy a screenshot to the clipboard and press `Ctrl+V` — no file
    needed. Elsewhere, install Pillow for clipboard image support, or just drag
    the image file in.

## The hint bar

You're never flying blind. The line under the prompt shows the most useful keys for the current state — `↑ history`, `/ commands`, `@ files`, `Ctrl+J multiline`, `Ctrl+K todos` when idle, and steering hints while the agent runs. Press `F1` any time for the full reference.

## Recap

- **Send and edit:** `Enter` sends, `Ctrl+J` toggles multiline, `↑`/`↓` walk history on an empty prompt.
- **Find and navigate:** `Ctrl+P` history picker, `Ctrl+R` message search, `PgUp`/`PgDn` scroll.
- **Panels and screens:** `Ctrl+K` todos, `Ctrl+L` clear, `F1` help, `F2` settings, `F5` context.
- **Control the agent:** `Ctrl+C`/`Esc` interrupt, `>>` steers, `!` runs shell, `Ctrl+D` quits.
- **Attach content:** `Ctrl+V` pastes images, drag-and-drop attaches files, multiline pastes are preserved automatically.

Next, make the CLI your own.

- [Settings & themes →](settings.md)
