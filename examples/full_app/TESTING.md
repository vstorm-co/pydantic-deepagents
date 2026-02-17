# Full App Demo — Testing Checklist

Complete testing checklist for all features in the pydantic-deep full_app demo.

---

## 1. Startup & Connection

- [x] App starts without errors: `uvicorn app:app --reload --port 8080`
- [x] Startup banner shows all features (hooks, middleware, processors, skills, subagents)
- [x] Frontend loads at http://localhost:8080
- [x] WebSocket connects automatically (send button enabled)
- [x] Session ID generated and stored in localStorage
- [x] Docker container created on first message

---

## 2. Chat — Basic

- [x] Send text message → agent responds with streamed text
- [x] Streaming text appears in real-time (word by word)
- [x] Agent response uses markdown formatting
- [x] Status line shows "Generating response..." during processing
- [x] Status line disappears when done
- [x] Enter sends message, Shift+Enter inserts newline
- [x] Empty message is rejected
- [x] Quick message buttons work (Query GitHub, Load Data Skill, etc.)

---

## 3. Markdown Rendering

- [x] **Bold** renders correctly
- [x] *Italic* renders correctly
- [x] ~~Strikethrough~~ renders correctly
- [x] `Inline code` renders with highlight
- [x] Code blocks (```) render with syntax highlighting
- [x] Code blocks show language label (python, javascript, etc.)
- [x] Code block copy button works
- [x] # Headers (h1-h4) render correctly
- [x] - Unordered lists render
- [x] 1. Ordered lists render
- [x] > Blockquotes render
- [x] --- Horizontal rules render
- [x] [Links](url) render as clickable links
- [x] | Tables | render correctly
- [x] File paths in messages are clickable (open preview)

---

## 4. Stop Button

- [x] Stop button appears when agent is generating (replaces send button)
- [x] Clicking stop cancels the agent run
- [x] "Stopped" label appears if cancelled before any text
- [x] Chat returns to normal state after cancel (send button reappears)
- [x] Can send new message after cancelling

---

## 5. File Attachments in Chat

- [x] Paperclip button opens file picker
- [x] Selected files appear as chips below input
- [x] Multiple files can be attached
- [x] Image thumbnails show in chips
- [x] File size shown in chips
- [x] Remove button (X) removes attachment
- [x] Paste image from clipboard (Ctrl+V) attaches it
- [x] Drag & drop files to chat area attaches them
- [x] Chat area highlights on drag over
- [x] Files are uploaded before message is sent
- [x] Upload paths mentioned in message to agent
- [x] Chips cleared after sending

---

## 6. Copy Message Button

- [x] Copy button appears on hover over assistant messages
- [x] Copy button NOT shown on user messages
- [x] Click copies plain text (no HTML) to clipboard
- [x] Checkmark feedback animation after copy
- [x] Button resets after 1.5 seconds

---

## 7. Tool Calls — Streaming

- [x] Tool call appears with name (e.g., `./read_file`)
- [x] Tool arguments stream in real-time
- [x] Status badge: STREAMING → running → done
- [x] Tool output appears after execution
- [x] Multiple tool calls shown sequentially
- [x] Parallel tool calls all displayed

---

## 8. Thinking (Extended Thinking)

- [ ] Thinking block appears with brain icon
- [ ] "Thinking..." label shown
- [ ] Thinking text streams in real-time
- [ ] Thinking block is visually distinct from response

---

## 9. Human-in-the-Loop (Approval)

- [x] **Test**: Ask agent to run a command (e.g., "Run `ls -la`")
- [x] Approval dialog appears with tool name and args
- [x] "Approve All" button allows execution → tool runs
- [x] "Deny All" button blocks execution → agent informed
- [x] Agent continues after approval/denial

---

## 10. Safety Gate Hook

- [x] **Test**: Ask agent to "Run `rm -rf /`"
- [x] Safety gate blocks the command
- [x] Hook event displayed in chat (blocked badge)
- [x] Agent receives denial reason and responds accordingly
- [x] **Test other patterns**: `:(){ :|:& };:` (fork bomb), `mkfs.ext4`, `chmod -R 777 /`

---

## 11. Permission Middleware

- [x] **Test**: Ask agent to "Read /etc/passwd"
- [x] Permission middleware blocks access
- [x] Agent receives denial message
- [x] **Test other paths**: `.env`, `/root/`, `/proc/cpuinfo`, `~/.ssh/id_rsa`

---

## 12. TODO List / Task Management

- [x] **Test**: Give multi-step task (e.g., "Create a script that generates prime numbers, test it, and save results")
- [x] Agent creates TODO list via write_todos
- [x] TODO widget appears in chat with items
- [x] Items show status icons: pending (circle), in_progress (spinner), completed (checkmark)
- [x] Progress counter updates (e.g., 2/5)
- [x] Completed items show strikethrough
- [x] In-progress items show activeForm text (e.g., "Writing script...")

---

## 13. Subagents

### 13a. Joke Generator
- [x] **Test**: "Tell me a joke about Python"
- [x] Agent delegates to joke-generator subagent
- [x] Subagent delegation visible in tool calls
- [x] Jokes returned and displayed

### 13b. Code Reviewer
- [x] **Test**: First create a file, then "Review the code in /workspace/script.py"
- [x] Agent delegates to code-reviewer subagent
- [x] Review returned with structured feedback

### 13c. General-Purpose Subagent
- [x] Built-in general-purpose subagent is available

---

## 14. Skills

### 14a. List Skills
- [x] **Test**: "List available skills"
- [x] Shows: data-analysis, code-review, test-generator, quick-reference

### 14b. Load Skill
- [x] **Test**: "Load the data-analysis skill"
- [x] Skill content loaded and applied to agent behavior

### 14c. Quick Reference (Programmatic)
- [x] **Test**: "Load the quick-reference skill"
- [x] Shows command shortcuts and usage guide

---

## 15. GitHub Tools (Mock Data)

- [x] **Test**: "List my GitHub repositories"
- [x] Returns mock repo list with stars/forks
- [x] **Test**: "Show open issues in pydantic-deep"
- [x] Returns mock issues with labels
- [x] **Test**: "Show pull requests for fastapi-starter"
- [x] Returns mock PRs with author and stats
- [x] **Test**: "Get info about user alice"
- [x] Returns mock user profile
- [x] **Test**: "Get stats for the ml-pipeline repo"
- [x] Returns detailed mock repo statistics

---

## 16. Code Execution (Docker Sandbox)

- [x] **Test**: "Write a Python script that prints hello world and save it to /workspace/hello.py"
- [x] File created in workspace
- [x] **Test**: "Run the script /workspace/hello.py"
- [x] Approval dialog appears (execute requires approval)
- [x] After approval, code runs in Docker container
- [x] Output displayed in tool result
- [x] **Test**: "Run `pip install requests && python -c 'import requests; print(requests.__version__)'`"
- [x] Package installs and runs in container

---

## 17. File Operations

- [x] **Test**: "List files in /workspace/"
- [x] Agent uses ls/glob tool
- [x] **Test**: "Create a file /workspace/test.txt with content 'hello world'"
- [x] File created, appears in workspace tab
- [x] **Test**: "Read /workspace/test.txt"
- [x] Content returned correctly
- [x] **Test**: "Edit /workspace/test.txt — change 'hello' to 'goodbye'"
- [x] File edited successfully
- [x] **Test**: "Search for 'goodbye' in workspace files"
- [x] grep tool finds the text

---

## 18. File Upload (Sidebar)

- [x] Click upload zone → file picker opens
- [x] Drag file onto upload zone → file uploads
- [x] Upload status shows filename
- [x] Success message appears in chat
- [x] File appears in Uploads tab
- [x] **Test with CSV**: Upload a CSV file → appears in list
- [x] **Test with image**: Upload a PNG → appears in list
- [x] **Test with PDF**: Upload a PDF → appears in list

---

## 19. File Preview Panel

### 19a. Code Files
- [x] Click .py file → preview opens with syntax highlighting
- [x] Click .js file → JavaScript highlighting
- [x] Click .json file → JSON highlighting
- [x] Click .md file → Markdown code view

### 19b. CSV Files
- [x] Click .csv file → table view with headers
- [x] Row numbers shown
- [x] Column count and row count displayed
- [x] Long cells truncated with hover tooltip
- [x] Handles commas in quoted fields

### 19c. Image Files
- [x] Click .png/.jpg → image displayed centered
- [x] Image scales to fit preview area

### 19d. HTML/SVG Preview
- [x] Click .html file → code view by default
- [x] Toggle to Preview mode → live preview in iframe
- [x] Relative CSS/JS paths resolve correctly
- [x] SVG files render in preview mode

### 19e. PDF Files
- [ ] Click .pdf → embedded PDF viewer

### 19f. Preview Actions
- [x] Copy button copies file content to clipboard
- [x] Download button downloads the file
- [x] Close button hides preview panel
- [x] Mode toggle (Code/Preview) shown only for HTML/SVG

---

## 20. Sidebar Tabs

### 20a. Uploads Tab
- [x] Shows flat list of uploaded files
- [x] Files clickable to open preview
- [x] File icons by extension

### 20b. Workspace Tab
- [x] Shows hierarchical folder tree
- [x] Folders expandable/collapsible
- [x] Folder icons change on expand
- [x] Files sorted alphabetically (folders first)
- [x] Files clickable to open preview
- [x] Refreshes after agent operations

### 20c. Config Tab
- [x] Shows Runtime info
- [x] Shows Hooks (count, names, event types, matchers)
- [x] Shows Middleware (count, names)
- [x] Shows Processors (eviction limit, sliding window, patch)
- [x] Shows Context Files
- [x] Shows Features (image support, interrupt_on)
- [x] Shows Subagents (names, descriptions)
- [x] Shows Skills (directories, programmatic)
- [x] Shows Tool Usage stats (live updates)

---

## 21. Config Panel — Live Stats

- [x] Total calls counter updates after each tool call
- [x] Total duration updates
- [x] Tools breakdown shows per-tool counts
- [x] Stats update in real-time during agent run

---

## 22. Middleware Events in Chat

- [ ] After tool calls, middleware audit event appears as subtle badge
- [ ] Shows tool name and call count
- [x] Blocked operations show red "BLOCKED" badge with reason

---

## 23. Session Management

- [x] Session persists across page refresh (same session_id)
- [x] Reset Session button shows confirmation dialog
- [x] After reset: chat cleared, files cleared, new container created
- [x] New session gets DEEP.md seeded in /workspace/

---

## 24. Sidebar Resizer

- [x] Drag handle between sidebar and main area
- [x] Sidebar resizes between 200px and 600px
- [x] Handle highlights on hover
- [x] Cursor changes during drag

---

## 25. WebSocket Reconnection

- [x] If server restarts, WebSocket reconnects automatically
- [x] Exponential backoff (up to 5 attempts)
- [x] Send button disabled while disconnected

---

## 26. Responsive Layout

- [x] At <1000px width, sidebar hides
- [x] Chat takes full width on mobile
- [x] Input and messages adjust padding

---

## 27. Context Files

- [x] DEEP.md exists in /workspace/ for each new session
- [x] Agent has workspace context in system prompt
- [x] **Test**: Ask "What's in the workspace?" → agent should know about DEEP.md

---

## 28. Processors

### 28a. Eviction Processor
- [x] Large tool outputs (>20K tokens) saved to file reference
- [x] **Test**: Generate very large output and check if evicted

### 28b. Sliding Window
- [x] After 50+ messages, old messages trimmed to keep 30
- [x] Agent still functions correctly after trimming

### 28c. Patch Tool Calls
- [x] Orphaned tool calls repaired on resume
- [x] No errors from malformed message history

---

## 29. Image Support

- [x] Upload an image (PNG/JPG)
- [x] **Test**: "What's in the image I uploaded?"
- [x] Agent reads image via multimodal read_file
- [x] Agent describes image content

---

## 30. Data Analysis Workflow (End-to-End)

- [x] Upload a CSV file (e.g., sales.csv)
- [x] "Load the data-analysis skill"
- [x] "Analyze the uploaded CSV and create a visualization"
- [x] Agent creates TODO list for steps
- [x] Agent reads the CSV
- [x] Agent writes and executes analysis script
- [x] Chart saved to /workspace/ (PNG or HTML)
- [x] Chart viewable in file preview
- [x] TODO items all marked completed

---

## Summary

| Category | Tests |
|----------|-------|
| Startup & Connection | 6 |
| Chat Basic | 8 |
| Markdown | 16 |
| Stop Button | 5 |
| File Attachments | 12 |
| Copy Message | 5 |
| Tool Calls | 6 |
| Thinking | 4 |
| Human-in-the-Loop | 5 |
| Safety Gate Hook | 5 |
| Permission Middleware | 4 |
| TODO List | 6 |
| Subagents | 7 |
| Skills | 5 |
| GitHub Tools | 10 |
| Code Execution | 6 |
| File Operations | 10 |
| File Upload | 8 |
| File Preview | 17 |
| Sidebar Tabs | 13 |
| Config Panel Stats | 4 |
| Middleware Events | 3 |
| Session Management | 4 |
| Sidebar Resizer | 4 |
| WebSocket Reconnection | 3 |
| Responsive Layout | 3 |
| Context Files | 3 |
| Processors | 6 |
| Image Support | 4 |
| Data Analysis E2E | 10 |
| **TOTAL** | **~200** |
