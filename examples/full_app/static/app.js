// pydantic-deep Demo Frontend with WebSocket Streaming

// WebSocket connection
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Session management
let sessionId = localStorage.getItem('sessionId') || null;

// State
let currentTab = 'uploads';

// DOM Elements
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const fileInput = document.getElementById('file-input');
const uploadArea = document.getElementById('upload-area');
const uploadStatus = document.getElementById('upload-status');
const filesList = document.getElementById('files-list');
const todosList = document.getElementById('todos-list');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    connectWebSocket();
    refreshFiles();
    refreshTodos();
});

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);

        // Try to reconnect
        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            setTimeout(connectWebSocket, 2000 * reconnectAttempts);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onmessage = handleWebSocketMessage;
}

function updateConnectionStatus(connected) {
    // Could add a visual indicator here
    sendBtn.disabled = !connected;
}

// Current message state for streaming
let currentMessageEl = null;
let currentToolsEl = null;
let streamedText = '';  // Accumulated streamed text

function handleWebSocketMessage(event) {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case 'session_created':
            // Server created a new session for us
            sessionId = data.session_id;
            localStorage.setItem('sessionId', sessionId);
            console.log('New session created:', sessionId);
            break;

        case 'start':
            // Create new message container for this response
            currentMessageEl = createMessageContainer('assistant');
            currentToolsEl = null;
            streamedText = '';  // Reset streamed text
            break;

        case 'status':
            updateStatus(data.content);
            break;

        case 'tool_call_start':
            // Tool call is starting - create placeholder with streaming args
            startToolCallStreaming(data.tool_name, data.tool_call_id);
            break;

        case 'tool_args_delta':
            // Streaming tool arguments chunk
            appendToolArgsDelta(data.tool_name, data.args_delta);
            break;

        case 'tool_start':
            // Tool execution is starting (after args are complete)
            addToolEvent(data.tool_name, data.args);
            break;

        case 'tool_output':
            updateToolOutput(data.tool_name, data.output);
            break;

        case 'text_delta':
            // Streaming text chunk - append to current message
            appendTextChunk(data.content);
            break;

        case 'thinking_delta':
            // Streaming thinking content (for reasoning models like o1)
            appendThinkingChunk(data.content);
            break;

        case 'response':
            // Final response - replace streaming content with formatted version
            if (currentMessageEl) {
                const contentEl = currentMessageEl.querySelector('.message-content');
                if (contentEl) {
                    contentEl.innerHTML = formatMessage(data.content);
                }
            }
            break;

        case 'done':
            finishMessage();
            refreshFiles();
            refreshTodos();
            break;

        case 'error':
            showError(data.content);
            break;

        case 'approval_required':
            showApprovalDialog(data.requests);
            break;
    }
}

function createMessageContainer(type) {
    const id = 'msg-' + Date.now();
    const messageEl = document.createElement('div');
    messageEl.className = `message ${type}`;
    messageEl.id = id;

    const label = type === 'user' ? 'You' : type === 'assistant' ? 'Agent' : 'System';

    messageEl.innerHTML = `
        <span class="message-label">${label}</span>
        <div class="message-tools"></div>
        <div class="message-content"></div>
    `;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return messageEl;
}

function updateStatus(status) {
    if (!currentMessageEl) return;

    let statusEl = currentMessageEl.querySelector('.message-status');
    if (!statusEl) {
        statusEl = document.createElement('div');
        statusEl.className = 'message-status';
        currentMessageEl.insertBefore(statusEl, currentMessageEl.querySelector('.message-content'));
    }
    statusEl.textContent = status;
}

// Streaming tool args accumulator
let streamingToolArgs = '';

function startToolCallStreaming(toolName, toolCallId) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    // Reset streaming args
    streamingToolArgs = '';

    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call streaming';
    toolEl.dataset.toolCallId = toolCallId || '';
    toolEl.innerHTML = `
        <div class="tool-header">
            <span class="tool-icon">&#9881;</span>
            <span class="tool-name">${escapeHtml(toolName)}</span>
            <span class="tool-status streaming">streaming args...</span>
        </div>
        <div class="tool-args streaming-args"><code></code></div>
        <div class="tool-output"></div>
    `;

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;

    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function appendToolArgsDelta(toolName, argsDelta) {
    if (!currentToolsEl) return;

    streamingToolArgs += argsDelta;

    const argsEl = currentToolsEl.querySelector('.tool-args code');
    if (argsEl) {
        argsEl.textContent = streamingToolArgs;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function addToolEvent(toolName, args) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    // Check if we already have a streaming tool element for this
    const existingStreamingTool = toolsEl.querySelector('.tool-call.streaming');
    if (existingStreamingTool) {
        // Update existing element with final args
        existingStreamingTool.classList.remove('streaming');
        const statusEl = existingStreamingTool.querySelector('.tool-status');
        if (statusEl) {
            statusEl.className = 'tool-status running';
            statusEl.textContent = 'running';
        }
        const argsEl = existingStreamingTool.querySelector('.tool-args');
        if (argsEl) {
            argsEl.className = 'tool-args';
            argsEl.innerHTML = formatToolArgs(args);
        }
        currentToolsEl = existingStreamingTool;
        return;
    }

    // Create new tool element (for non-streamed tools)
    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call';
    toolEl.innerHTML = `
        <div class="tool-header">
            <span class="tool-icon">&#9881;</span>
            <span class="tool-name">${escapeHtml(toolName)}</span>
            <span class="tool-status running">running</span>
        </div>
        <div class="tool-args">${formatToolArgs(args)}</div>
        <div class="tool-output"></div>
    `;

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;

    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function formatToolArgs(args) {
    if (typeof args === 'string') {
        try {
            args = JSON.parse(args);
        } catch {
            return `<code>${escapeHtml(args)}</code>`;
        }
    }

    if (typeof args === 'object') {
        const parts = [];
        for (const [key, value] of Object.entries(args)) {
            const displayValue = typeof value === 'string' && value.length > 100
                ? value.substring(0, 100) + '...'
                : JSON.stringify(value);
            parts.push(`<span class="arg-key">${escapeHtml(key)}:</span> <span class="arg-value">${escapeHtml(displayValue)}</span>`);
        }
        return parts.join('<br>');
    }

    return '';
}

function updateToolOutput(toolName, output) {
    if (!currentToolsEl) return;

    const outputEl = currentToolsEl.querySelector('.tool-output');
    const statusEl = currentToolsEl.querySelector('.tool-status');

    if (outputEl) {
        outputEl.innerHTML = `<pre>${escapeHtml(output)}</pre>`;
    }

    if (statusEl) {
        statusEl.className = 'tool-status done';
        statusEl.textContent = 'done';
    }
}

function appendTextChunk(chunk) {
    if (!currentMessageEl) return;

    streamedText += chunk;

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (contentEl) {
        // Use textContent for streaming (faster), will be replaced with formatted HTML on 'response'
        contentEl.textContent = streamedText;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function appendThinkingChunk(chunk) {
    if (!currentMessageEl) return;

    // Get or create thinking container
    let thinkingEl = currentMessageEl.querySelector('.message-thinking');
    if (!thinkingEl) {
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'message-thinking';
        thinkingEl.innerHTML = '<span class="thinking-label">💭 Thinking...</span><div class="thinking-content"></div>';
        const contentEl = currentMessageEl.querySelector('.message-content');
        currentMessageEl.insertBefore(thinkingEl, contentEl);
    }

    const thinkingContent = thinkingEl.querySelector('.thinking-content');
    if (thinkingContent) {
        thinkingContent.textContent += chunk;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function finishMessage() {
    if (currentMessageEl) {
        // Remove status indicator
        const statusEl = currentMessageEl.querySelector('.message-status');
        if (statusEl) {
            statusEl.remove();
        }

        // Mark all tools as done
        const toolStatuses = currentMessageEl.querySelectorAll('.tool-status.running');
        toolStatuses.forEach(el => {
            el.className = 'tool-status done';
            el.textContent = 'done';
        });
    }

    currentMessageEl = null;
    currentToolsEl = null;
    sendBtn.disabled = false;
}

function showError(message) {
    if (currentMessageEl) {
        const contentEl = currentMessageEl.querySelector('.message-content');
        if (contentEl) {
            contentEl.innerHTML = `<span class="error">Error: ${escapeHtml(message)}</span>`;
        }
    } else {
        addMessage(`Error: ${message}`, 'system');
    }

    finishMessage();
}

// Pending approval requests
let pendingApprovals = [];

function showApprovalDialog(requests) {
    pendingApprovals = requests;

    // Create approval UI in the current message
    if (!currentMessageEl) {
        currentMessageEl = createMessageContainer('assistant');
    }

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (!contentEl) return;

    let html = '<div class="approval-dialog">';
    html += '<h4>Approval Required</h4>';
    html += '<p>The following operations require your approval:</p>';

    for (const req of requests) {
        html += `
            <div class="approval-item" data-id="${req.tool_call_id}">
                <div class="approval-tool">
                    <span class="tool-icon">&#9881;</span>
                    <strong>${escapeHtml(req.tool_name)}</strong>
                </div>
                <div class="approval-args">${formatToolArgs(req.args)}</div>
            </div>
        `;
    }

    html += `
        <div class="approval-buttons">
            <button class="approve-btn" onclick="handleApprovalResponse(true)">Approve All</button>
            <button class="deny-btn" onclick="handleApprovalResponse(false)">Deny All</button>
        </div>
    </div>`;

    contentEl.innerHTML = html;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function handleApprovalResponse(approved) {
    if (!pendingApprovals.length) return;

    // Build approval response
    const approvalResponse = {};
    for (const req of pendingApprovals) {
        approvalResponse[req.tool_call_id] = approved;
    }

    // Clear pending
    pendingApprovals = [];

    // Update UI
    if (currentMessageEl) {
        const contentEl = currentMessageEl.querySelector('.message-content');
        if (contentEl) {
            contentEl.innerHTML = `<p>${approved ? 'Approved' : 'Denied'} - continuing...</p>`;
        }
    }

    // Send approval response via WebSocket
    ws.send(JSON.stringify({ approval: approvalResponse }));
}

function setupEventListeners() {
    // Message input
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + 'px';
    });

    // File upload
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadFile(files[0]);
        }
    });

    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;
            refreshFiles();
        });
    });
}

// Chat Functions
function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addMessage('Not connected to server. Reconnecting...', 'system');
        connectWebSocket();
        return;
    }

    // Clear input
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Add user message
    addMessage(message, 'user');

    // Disable send button while processing
    sendBtn.disabled = true;

    // Send via WebSocket with session_id
    const payload = { message };
    if (sessionId) {
        payload.session_id = sessionId;
    }
    ws.send(JSON.stringify(payload));
}

function sendQuickMessage(message) {
    messageInput.value = message;
    sendMessage();
}

function addMessage(content, type) {
    const id = 'msg-' + Date.now();
    const messageEl = document.createElement('div');
    messageEl.className = `message ${type}`;
    messageEl.id = id;

    const label = type === 'user' ? 'You' : type === 'assistant' ? 'Agent' : 'System';

    messageEl.innerHTML = `
        <span class="message-label">${label}</span>
        <div class="message-content">${formatMessage(content)}</div>
    `;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return id;
}

function formatMessage(content) {
    // Convert markdown-like syntax to HTML
    let html = escapeHtml(content);

    // Code blocks
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    return html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// File Functions
function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        uploadFile(file);
    }
}

async function uploadFile(file) {
    uploadStatus.textContent = `Uploading ${file.name}...`;
    uploadStatus.className = '';

    const formData = new FormData();
    formData.append('file', file);

    // Build URL with session_id
    let url = '/upload';
    if (sessionId) {
        url += `?session_id=${encodeURIComponent(sessionId)}`;
    }

    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            uploadStatus.textContent = `Uploaded: ${data.filename}`;
            uploadStatus.className = 'success';
            refreshFiles();

            // Add system message about upload
            addMessage(`File uploaded: ${data.filename} (${formatBytes(data.size)})`, 'system');
        } else {
            uploadStatus.textContent = `Error: ${data.detail}`;
            uploadStatus.className = 'error';
        }
    } catch (error) {
        uploadStatus.textContent = `Error: ${error.message}`;
        uploadStatus.className = 'error';
    }

    // Clear input
    fileInput.value = '';

    // Clear status after 3 seconds
    setTimeout(() => {
        uploadStatus.textContent = '';
        uploadStatus.className = '';
    }, 3000);
}

async function refreshFiles() {
    if (!sessionId) return;  // No session yet

    try {
        const response = await fetch(`/files?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) return;  // Session may not exist yet
        const data = await response.json();

        const files = currentTab === 'uploads' ? data.uploads : data.workspace;

        if (files.length === 0) {
            filesList.innerHTML = '<p class="empty-state">No files yet</p>';
            return;
        }

        filesList.innerHTML = files.map(file => {
            const name = typeof file === 'string' ? file.split('/').pop() : file;
            const downloadLink = currentTab === 'workspace'
                ? `<a href="/files/download/${file}" target="_blank">&#11015;</a>`
                : '';
            return `
                <div class="file-item">
                    <span title="${file}">${name}</span>
                    ${downloadLink}
                </div>
            `;
        }).join('');
    } catch (error) {
        filesList.innerHTML = '<p class="empty-state">Error loading files</p>';
    }
}

async function refreshTodos() {
    if (!sessionId) return;  // No session yet

    try {
        const response = await fetch(`/todos?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) return;  // Session may not exist yet
        const data = await response.json();

        if (!data.todos || data.todos.length === 0) {
            todosList.innerHTML = '<p class="empty-state">No todos yet</p>';
            return;
        }

        todosList.innerHTML = data.todos.map(todo => `
            <div class="todo-item">
                <div class="todo-status ${todo.status}"></div>
                <span>${escapeHtml(todo.content)}</span>
            </div>
        `).join('');
    } catch (error) {
        todosList.innerHTML = '<p class="empty-state">Error loading todos</p>';
    }
}

async function resetAgent() {
    if (!confirm('Are you sure you want to reset the agent? This will clear all files and history.')) {
        return;
    }

    try {
        if (sessionId) {
            await fetch(`/reset?session_id=${encodeURIComponent(sessionId)}`, { method: 'POST' });
        }
        // Clear session ID - will get a new one on reconnect
        sessionId = null;
        localStorage.removeItem('sessionId');

        // Clear messages except welcome
        messagesContainer.innerHTML = '';
        addMessage(`
            <p><strong>Agent Reset!</strong> Ready to start fresh.</p>
            <ul>
                <li><strong>File Operations</strong> - Upload CSV/PDF, read, write, edit files</li>
                <li><strong>GitHub Tools</strong> - Query repos, issues, PRs (mock data)</li>
                <li><strong>Code Execution</strong> - Run Python in a Docker sandbox</li>
                <li><strong>Data Analysis</strong> - Load the skill for CSV analysis</li>
                <li><strong>Joke Generator</strong> - Ask me to tell jokes!</li>
            </ul>
        `, 'system');

        refreshFiles();
        refreshTodos();

        // Reconnect WebSocket
        if (ws) {
            ws.close();
        }
        connectWebSocket();
    } catch (error) {
        alert('Error resetting agent: ' + error.message);
    }
}

// Utility
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}
