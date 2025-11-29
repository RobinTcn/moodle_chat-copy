// src/App.tsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { ChatResponse } from './ChatResponse';
import BottomNav from './BottomNav';
import Calendar from './Calendar';

interface Message {
  sender: "user" | "bot";
  text: string;
}

// Minimal HTML-escaping to avoid accidental HTML injection when converting Markdown.
function escapeHtml(unsafe: string) {
  return unsafe
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/\'/g, "&#039;");
}

// Very small Markdown -> HTML converter for common formatting used by Gemini.
// Handles headings (#), bold (**), italic (*), inline code (`), code blocks (```), links and lists.
function markdownToHtml(md: string) {
  if (!md) return '';
  // Normalize CRLF
  let out = md.replace(/\r\n/g, "\n");

  // Escape to prevent HTML injection, then selectively re-introduce safe tags
  out = escapeHtml(out);

  // Code blocks ```
  out = out.replace(/```([\s\S]*?)```/g, (_m, code) => {
    return '<pre><code>' + escapeHtml(code) + '</code></pre>';
  });

  // Inline code `code`
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Headings
  out = out.replace(/^######\s*(.*)$/gm, '<h6>$1</h6>');
  out = out.replace(/^#####\s*(.*)$/gm, '<h5>$1</h5>');
  out = out.replace(/^####\s*(.*)$/gm, '<h4>$1</h4>');
  out = out.replace(/^###\s*(.*)$/gm, '<h3>$1</h3>');
  out = out.replace(/^##\s*(.*)$/gm, '<h2>$1</h2>');
  out = out.replace(/^#\s*(.*)$/gm, '<h1>$1</h1>');

  // Bold **text**
  out = out.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic *text*
  out = out.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // Links [text](url)
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Simple unordered lists: lines starting with '- '
  // Convert consecutive lines into a single <ul>
  out = out.replace(/(^|\n)(?:-\s+.*(?:\n|$))+/g, (match) => {
    const items = match.trim().split(/\n/).map(l => l.replace(/^-\s+/, ''));
    return '\n<ul>' + items.map(i => '<li>' + i + '</li>').join('') + '</ul>\n';
  });

  // Convert double newlines to paragraphs
  out = out.replace(/\n{2,}/g, '</p><p>');
  // Single newlines to <br />
  out = out.replace(/\n/g, '<br />');

  // Wrap with paragraph if not already block-level
  if (!out.match(/^\s*<(?:h1|h2|h3|h4|h5|h6|ul|pre|p|blockquote)/i)) {
    out = '<p>' + out + '</p>';
  }

  return out;
}

// If the backend returned raw HTML (contains tags) trust it as HTML; otherwise convert Markdown -> HTML.
function renderMarkup(text: string) {
  if (!text) return '';
  // Convert leading '*' bullets (e.g. '* In 3 Tagen...') to '-' so they become proper markdown list items
  // This removes the superfluous asterisks while preserving a list structure.
  text = text.replace(/(^|\n)\*\s+/g, '$1- ');

  // crude HTML detection: if there is an HTML tag present, treat as HTML
  const hasHtmlTag = /<[^>]+>/.test(text);
  if (hasHtmlTag) {
    // We assume the backend may send intended HTML. Return as-is.
    return text;
  }
  // Otherwise, treat as Markdown and convert
  return markdownToHtml(text);
}

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [selectedTab, setSelectedTab] = useState<"calendar"|"chat"|"settings">("chat");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Load saved credentials from localStorage on first render
  useEffect(() => {
    try {
      const su = localStorage.getItem('moodle_username');
      const sp = localStorage.getItem('moodle_password');
      if (su) setUsername(su);
      if (sp) setPassword(sp);
    } catch (e) {
      // ignore (e.g. localStorage not available)
    }
  }, []);

  // Persist credentials to localStorage whenever they change
  useEffect(() => {
    try {
      if (username) localStorage.setItem('moodle_username', username);
      else localStorage.removeItem('moodle_username');
      if (password) localStorage.setItem('moodle_password', password);
      else localStorage.removeItem('moodle_password');
    } catch (e) {
      // ignore
    }
  }, [username, password]);

  const clearCredentials = () => {
    setUsername("");
    setPassword("");
    try {
      localStorage.removeItem('moodle_username');
      localStorage.removeItem('moodle_password');
    } catch (e) {}
  };

  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); };
  useEffect(scrollToBottom, [messages]);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMessage = input;
    setInput("");

    // typing indicator HTML (will be rendered as HTML by the bot bubble)
    const typingHtml = '<div class="typing-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';

    // Add user message and typing indicator atomically
    setMessages(prev => [...prev, { sender: "user", text: userMessage }, { sender: "bot", text: typingHtml }]);

    try {
      const res = await axios.post<ChatResponse>("http://127.0.0.1:8000/chat", {
        message: userMessage,
        username,
        password
      });
      // Replace the typing indicator (last message) with the real response
      setMessages(prev => {
        const withoutTyping = prev.slice(0, -1); // drop last (typing)
        return [...withoutTyping, { sender: "bot", text: res.data.response }];
      });
    } catch {
      setMessages(prev => {
        const withoutTyping = prev.slice(0, -1);
        return [...withoutTyping, { sender: "bot", text: "Fehler beim Server." }];
      });
    }
  };

  const handleKey = (e: React.KeyboardEvent) => { if (e.key==="Enter") sendMessage(); };

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* Top header: simple title */}
      <div className="p-4 bg-white border-b flex items-center justify-center">
        <h1 className="text-lg font-semibold">StudiBot</h1>
      </div>

      {/* Main content area. We add bottom padding so the bottom nav doesn't overlap content. */}
      <div className="flex-1 overflow-y-auto p-4 pb-24">
        {selectedTab === "calendar" && (
          <div className="h-full">
            <Calendar />
          </div>
        )}

        {selectedTab === "chat" && (
          <div>
            {messages.map((m,i)=>(
              <div key={i} className={`flex mb-2 ${m.sender==="user"?"justify-end":"justify-start"}`}>
                <div className={`rounded-lg p-3 max-w-lg ${m.sender==="user"?"bg-green-500 text-white":"bg-gray-300 text-black"}`}>
                  {/* Render bot/user text. Support simple HTML or Markdown from the backend. */}
                  {m.sender === "bot" ? (
                    <div
                      // We intentionally allow limited HTML from the backend. Convert simple Markdown to HTML first.
                      dangerouslySetInnerHTML={{ __html: renderMarkup(m.text) }}
                    />
                  ) : (
                    // Render user message as plain text to avoid accidental HTML rendering
                    <div>{m.text}</div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />

            {/* Chat input: lifted above the bottom nav, rounded container and pill-shaped controls */}
            <div className="fixed left-0 right-0 bottom-24 flex p-4 max-w-4xl mx-auto w-full z-20">
              <div className="mx-auto flex w-full max-w-4xl bg-white rounded-xl shadow-lg ring-1 ring-gray-200 px-2 py-2 items-center gap-2">
                <input 
                  type="text" 
                  className="flex-1 border-0 outline-none px-4 py-2 rounded-full"
                  value={input} 
                  onChange={e=>setInput(e.target.value)} 
                  onKeyDown={handleKey}
                  placeholder="Schreibe eine Nachricht..."
                />
                <button onClick={sendMessage} className="bg-green-500 hover:bg-green-600 text-white px-5 py-2 rounded-full shadow">Senden</button>
              </div>
            </div>
          </div>
        )}

        {selectedTab === "settings" && (
          <div className="max-w-xl mx-auto">
            <h2 className="text-lg font-medium mb-4">Einstellungen</h2>
            <label className="block mb-2 text-sm text-gray-700">Benutzername</label>
            <input type="text" placeholder="Benutzername" className="border rounded-lg p-2 w-full mb-4" value={username} onChange={e=>setUsername(e.target.value)} />
            <label className="block mb-2 text-sm text-gray-700">Passwort</label>
            <input type="password" placeholder="Passwort" className="border rounded-lg p-2 w-full mb-4" value={password} onChange={e=>setPassword(e.target.value)} />
            <div className="text-sm text-gray-500">Die Anmeldedaten werden lokal gespeichert und beim Senden einer Nachricht an das Backend verwendet. Keine Sorge, sie werden an keine dritte Partei weitergegeben.</div>
            <div className="mt-4">
              <button onClick={clearCredentials} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg">Anmeldedaten löschen</button>
            </div>
          </div>
        )}
      </div>

      {/* Bottom navigation (extracted) */}
      <BottomNav selectedTab={selectedTab} onSelect={setSelectedTab} />
    </div>
  );
}

export default App;
