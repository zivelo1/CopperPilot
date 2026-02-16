# Open-Source Chat Widget Options

## Current Implementation
We have a **simple HTML + WebSocket chat** that's functional and clean. However, here are some open-source alternatives that could enhance the experience:

## 1. **Chatbot-UI** ⭐ RECOMMENDED
- **GitHub**: https://github.com/mckaywrigley/chatbot-ui
- **Pros**:
  - Clean, modern interface similar to ChatGPT
  - Markdown support with syntax highlighting
  - File upload support built-in
  - Conversation history
  - Mobile responsive
- **Cons**: React-based (more complex to integrate)
- **Integration Effort**: Medium (2-3 hours)

## 2. **Botpress Webchat**
- **GitHub**: https://github.com/botpress/botpress
- **Pros**:
  - Professional appearance
  - Typing indicators
  - Rich media support
  - Customizable themes
- **Cons**: Designed for Botpress platform
- **Integration Effort**: High (4-5 hours)

## 3. **React Chat Widget**
- **GitHub**: https://github.com/Wolox/react-chat-widget
- **Pros**:
  - Lightweight and simple
  - Easy to customize
  - Good for embedding
- **Cons**: Basic features only
- **Integration Effort**: Low (1-2 hours)

## 4. **Socket.io Chat**
- **GitHub**: https://github.com/socketio/socket.io
- **Pros**:
  - Battle-tested WebSocket library
  - Real-time features
  - Reconnection handling
- **Cons**: Just a library, not a widget
- **Integration Effort**: Already using WebSockets

## 5. **Chatwoot** (Full Platform)
- **GitHub**: https://github.com/chatwoot/chatwoot
- **Pros**:
  - Full customer support platform
  - Analytics and reporting
  - Multi-channel support
- **Cons**: Overkill for this project
- **Integration Effort**: Very High

## My Recommendation

**Stick with current implementation for now**, but consider these enhancements:

### Quick Improvements to Current Chat (30 minutes):
```javascript
// 1. Add Markdown support
function renderMarkdown(text) {
    // Use marked.js library
    return marked.parse(text);
}

// 2. Add typing indicator
function showTyping() {
    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = '<span></span><span></span><span></span>';
    chatMessages.appendChild(indicator);
}

// 3. Add file preview
function previewFile(file) {
    if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (e) => {
            addMessage(`<img src="${e.target.result}" style="max-width: 200px;">`, 'user');
        };
        reader.readAsDataURL(file);
    }
}

// 4. Add conversation export
function exportChat() {
    const messages = Array.from(chatMessages.children).map(m => m.textContent);
    const blob = new Blob([messages.join('\n')], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-${currentProjectId}.txt`;
    a.click();
}
```

### CSS Enhancements:
```css
/* Typing indicator animation */
.typing-indicator {
    padding: 10px;
}

.typing-indicator span {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #999;
    margin: 0 2px;
    animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
    animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
    animation-delay: 0.4s;
}

@keyframes typing {
    0%, 60%, 100% {
        opacity: 0.3;
        transform: translateY(0);
    }
    30% {
        opacity: 1;
        transform: translateY(-10px);
    }
}

/* Code block styling */
.message pre {
    background: #f5f5f5;
    padding: 10px;
    border-radius: 5px;
    overflow-x: auto;
}

.message code {
    background: #f0f0f0;
    padding: 2px 4px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
}
```

## Decision

The current simple HTML + WebSocket implementation is actually quite good for MVP. It's:
- ✅ Working
- ✅ Clean and professional
- ✅ No dependencies
- ✅ Easy to debug

**Suggested approach:**
1. Use current implementation to get system working
2. Add the quick improvements above
3. Consider Chatbot-UI later if needed for production

Would you like me to:
1. Keep the current simple implementation? ✓
2. Add the quick improvements mentioned above?
3. Integrate one of the open-source options?