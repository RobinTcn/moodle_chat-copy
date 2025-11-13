// src/App.tsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { ChatResponse } from './ChatResponse';

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

  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); };
  useEffect(scrollToBottom, [messages]);

  const sendMessage = async () => {
    if (!input.trim()) return;
    setMessages([...messages, { sender: "user", text: input }]);
    const userMessage = input;
    setInput("");
    try {
      const res = await axios.post<ChatResponse>("http://127.0.0.1:8000/chat", { 
        message: userMessage, 
        username, 
        password 
      });
      setMessages(prev => [...prev, { sender: "bot", text: res.data.response }]);
    } catch {
      setMessages(prev => [...prev, { sender: "bot", text: "Fehler beim Server." }]);
    }
  };

  const handleKey = (e: React.KeyboardEvent) => { if (e.key==="Enter") sendMessage(); };

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      {/* Top header: simple title */}
      <div className="p-4 bg-white border-b flex items-center justify-center">
        <h1 className="text-lg font-semibold">Moodle Chat</h1>
      </div>

      {/* Main content area. We add bottom padding so the bottom nav doesn't overlap content. */}
      <div className="flex-1 overflow-y-auto p-4 pb-24">
        {selectedTab === "calendar" && (
          <div className="h-full flex items-center justify-center">
            <div className="text-gray-500">Kalender (Platzhalter)</div>
          </div>
        )}

        {selectedTab === "chat" && (
          <div>
            {messages.map((m,i)=>(
              <div key={i} className={`flex mb-2 ${m.sender==="user"?"justify-end":"justify-start"}`}>
                <div className={`rounded-lg p-3 max-w-xs ${m.sender==="user"?"bg-green-500 text-white":"bg-gray-300 text-black"}`}>
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

            {/* Chat input: fixed to bottom of view but inside content area we keep it at the bottom visually by placing it here. */}
            <div className="fixed left-0 right-0 bottom-16 flex p-4 bg-white border-t max-w-4xl mx-auto w-full">
              <div className="mx-auto flex w-full max-w-4xl">
                <input 
                  type="text" 
                  className="flex-1 border rounded-lg p-2 mr-2"
                  value={input} 
                  onChange={e=>setInput(e.target.value)} 
                  onKeyDown={handleKey}
                />
                <button onClick={sendMessage} className="bg-green-500 text-white px-4 rounded-lg">Senden</button>
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
            <div className="text-sm text-gray-500">Die Anmeldedaten werden beim Senden einer Nachricht an das Backend verwendet. Keine Sorge, sie werden nicht gespeichert oder an eine dritte Partei weitergegeben.</div>
          </div>
        )}
      </div>

      {/* Bottom navigation */}
      <div className="fixed left-0 right-0 bottom-0 bg-white border-t">
        <div className="max-w-4xl mx-auto flex justify-between">
          <button onClick={()=>setSelectedTab("calendar")} className={`w-1/3 p-3 text-center ${selectedTab==="calendar"?"text-green-600 font-semibold":"text-gray-600"}`}>
            Kalender
          </button>
          <button onClick={()=>setSelectedTab("chat")} className={`w-1/3 p-3 text-center ${selectedTab==="chat"?"text-green-600 font-semibold":"text-gray-600"}`}>
            Chat
          </button>
          <button onClick={()=>setSelectedTab("settings")} className={`w-1/3 p-3 text-center ${selectedTab==="settings"?"text-green-600 font-semibold":"text-gray-600"}`}>
            Einstellungen
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
