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
  const [apiKey, setApiKey] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [showApiModal, setShowApiModal] = useState(false);
  const [selectedTab, setSelectedTab] = useState<"calendar"|"chat"|"settings">("chat");
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('darkMode');
    return saved ? JSON.parse(saved) : false;
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const backendBase = "http://127.0.0.1:8000";

  // Persist dark mode preference
  useEffect(() => {
    localStorage.setItem('darkMode', JSON.stringify(darkMode));
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  // Load saved credentials from backend on first render
  useEffect(() => {
    (async () => {
      try {
        const res = await axios.get<{ username?: string; password?: string; api_key?: string }>(`${backendBase}/credentials/load`);
        if (res.data.username) setUsername(res.data.username);
        if (res.data.password) setPassword(res.data.password);
        if (res.data.api_key) {
          setApiKey(res.data.api_key);
          setApiKeyInput(res.data.api_key);
        } else {
          setShowApiModal(true);
        }
      } catch (e) {
        // Backend not available or no credentials stored
        setShowApiModal(true);
      }
    })();
  }, []);

  // Persist credentials to backend whenever they change
  useEffect(() => {
    if (!username || !password || !apiKey) return;
    (async () => {
      try {
        await axios.post(`${backendBase}/credentials/save`, {
          username,
          password,
          api_key: apiKey
        });
      } catch (e) {
        console.error('Failed to save credentials:', e);
      }
    })();
  }, [username, password, apiKey]);

  const clearCredentials = async () => {
    setUsername("");
    setPassword("");
    try {
      await axios.delete(`${backendBase}/credentials/delete`);
    } catch (e) {
      console.error('Failed to delete credentials:', e);
    }
  };

  const saveApiKey = async () => {
    const trimmed = apiKeyInput.trim();
    if (!trimmed) return;
    setApiKey(trimmed);
    setShowApiModal(false);
    // API key wird automatisch durch useEffect gespeichert
  };

  const clearApiKey = async () => {
    setApiKey("");
    setApiKeyInput("");
    try {
      await axios.delete(`${backendBase}/credentials/delete`);
    } catch (e) {
      console.error('Failed to delete API key:', e);
    }
    setShowApiModal(true);
  };

  const scrollToBottom = () => { messagesEndRef.current?.scrollIntoView({ behavior: "smooth" }); };
  useEffect(scrollToBottom, [messages]);

  const sendMessage = async () => {
    if (!input.trim()) return;
    if (!apiKey) {
      setShowApiModal(true);
      return;
    }
    const userMessage = input;
    setInput("");

    // typing indicator HTML (will be rendered as HTML by the bot bubble)
    const typingHtml = '<div class="typing-bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';

    // Add user message and typing indicator atomically
    setMessages(prev => [...prev, { sender: "user", text: userMessage }, { sender: "bot", text: typingHtml }]);

    try {
      const res = await axios.post<ChatResponse>(`${backendBase}/chat`, {
        message: userMessage,
        username,
        password,
        api_key: apiKey
      });
      // Replace the typing indicator (last message) with the real response
      setMessages(prev => {
        const withoutTyping = prev.slice(0, -1); // drop last (typing)
        return [...withoutTyping, { sender: "bot", text: res.data.response }];
      });

      // If the backend returned an ICS filename, append a download button message
      if (res.data && res.data.ics_filename) {
        const url = `${backendBase}/download_ics/${encodeURIComponent(res.data.ics_filename)}`;
        const btnHtml = `<div style="margin-top:6px"><a href="${url}" download class="inline-block bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded">Kalender herunterladen (.ics)</a></div>`;
        setMessages(prev => [...prev, { sender: "bot", text: btnHtml }]);
      }
    } catch {
      setMessages(prev => {
        const withoutTyping = prev.slice(0, -1);
        return [...withoutTyping, { sender: "bot", text: "Fehler beim Server." }];
      });
    }
  };

  const handleKey = (e: React.KeyboardEvent) => { if (e.key==="Enter") sendMessage(); };

  return (
    <div className={`flex flex-col h-screen ${darkMode ? 'bg-gray-900' : 'bg-gray-100'}`}>
      {/* Top header: simple title with dark mode toggle */}
      <div className={`p-4 border-b flex items-center justify-between ${darkMode ? 'bg-gray-800 border-gray-700' : 'bg-white'}`}>
        <div className="flex-1" />
        <h1 className={`text-lg font-semibold ${darkMode ? 'text-white' : 'text-black'}`}>StudiBot</h1>
        <div className="flex-1 flex justify-end">
          <button
            onClick={() => setDarkMode(!darkMode)}
            className={`p-2 rounded-lg transition-colors ${darkMode ? 'bg-gray-700 hover:bg-gray-600 text-yellow-400' : 'bg-gray-100 hover:bg-gray-200 text-gray-700'}`}
            aria-label="Toggle dark mode"
          >
            {darkMode ? (
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" />
              </svg>
            ) : (
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Main content area. We add bottom padding so the bottom nav and chat input don't overlap content. */}
      <div className="flex-1 overflow-y-auto p-4 pb-56">
        {selectedTab === "calendar" && (
          <div className="h-full">
            <Calendar />
          </div>
        )}

        {selectedTab === "chat" && (
          <div>
            {messages.map((m,i)=>(
              <div key={i} className={`flex mb-2 ${m.sender==="user"?"justify-end":"justify-start"}`}>
                <div className={`rounded-lg p-3 max-w-lg ${m.sender==="user"?"bg-green-500 text-white":darkMode?"bg-gray-700 text-white":"bg-gray-300 text-black"}`}>
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
              <div className={`mx-auto flex w-full max-w-4xl rounded-xl shadow-lg ring-1 px-2 py-2 items-center gap-2 ${darkMode ? 'bg-gray-800 ring-gray-700' : 'bg-white ring-gray-200'}`}>
                <input 
                  type="text" 
                  className={`flex-1 border-0 outline-none px-4 py-2 rounded-full ${darkMode ? 'bg-gray-700 text-white placeholder-gray-400' : 'bg-white text-black'}`}
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
            <h2 className={`text-lg font-medium mb-4 ${darkMode ? 'text-white' : 'text-black'}`}>Einstellungen</h2>
            <label className={`block mb-2 text-sm ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>Benutzername</label>
            <input type="text" placeholder="Benutzername" className={`border rounded-lg p-2 w-full mb-4 ${darkMode ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' : 'bg-white border-gray-300'}`} value={username} onChange={e=>setUsername(e.target.value)} />
            <label className={`block mb-2 text-sm ${darkMode ? 'text-gray-300' : 'text-gray-700'}`}>Passwort</label>
            <input type="password" placeholder="Passwort" className={`border rounded-lg p-2 w-full mb-4 ${darkMode ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' : 'bg-white border-gray-300'}`} value={password} onChange={e=>setPassword(e.target.value)} />
            <div className={`text-sm ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Die Anmeldedaten werden lokal gespeichert und beim Senden einer Nachricht an das Backend verwendet. Keine Sorge, sie werden an keine dritte Partei weitergegeben.</div>
            <div className="mt-4">
              <button onClick={clearCredentials} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg">Anmeldedaten löschen</button>
            </div>

            <div className="mt-8">
              <h3 className={`text-md font-medium mb-2 ${darkMode ? 'text-white' : 'text-black'}`}>ChatGPT API-Key</h3>
              <input
                type="password"
                placeholder="sk-..."
                className={`border rounded-lg p-2 w-full mb-2 ${darkMode ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' : 'bg-white border-gray-300'}`}
                value={apiKeyInput}
                onChange={e=>setApiKeyInput(e.target.value)}
              />
              <div className="flex gap-2">
                <button onClick={saveApiKey} className="bg-green-500 hover:bg-green-600 text-white px-4 py-2 rounded-lg">API-Key speichern</button>
                <button onClick={clearApiKey} className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg">API-Key löschen</button>
              </div>
              <div className={`text-xs mt-2 ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>Der Key wird nur lokal gespeichert und bei API-Aufrufen mitgeschickt.</div>
            </div>
          </div>
        )}
      </div>

      {showApiModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className={`rounded-lg shadow-lg p-5 max-w-sm w-full ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
            <h3 className={`text-lg font-medium mb-2 ${darkMode ? 'text-white' : 'text-black'}`}>API-Key erforderlich</h3>
            <p className={`text-sm mb-3 ${darkMode ? 'text-gray-300' : 'text-gray-600'}`}>Bitte gib deinen ChatGPT API-Key ein. Er wird nur lokal gespeichert und für die Anfragen genutzt.</p>
            <input
              type="password"
              placeholder="sk-..."
              className={`border rounded-lg p-2 w-full mb-3 ${darkMode ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400' : 'bg-white border-gray-300'}`}
              value={apiKeyInput}
              onChange={e => setApiKeyInput(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowApiModal(false)} className={`px-3 py-2 rounded border ${darkMode ? 'border-gray-600 text-gray-300 hover:bg-gray-700' : 'border-gray-300 hover:bg-gray-50'}`}>Später</button>
              <button onClick={saveApiKey} className="bg-green-500 hover:bg-green-600 text-white px-4 py-2 rounded">Speichern</button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom navigation (extracted) */}
      <BottomNav selectedTab={selectedTab} onSelect={setSelectedTab} darkMode={darkMode} />
    </div>
  );
}

export default App;
