// src/App.tsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import 'katex/dist/katex.min.css';
import { ChatResponse, CalendarEventSuggestion } from './ChatResponse';
import BottomNav from './BottomNav';
import Calendar from './Calendar';

declare global {
  interface Window {
    addCalendarEvent: (date: string, title: string) => void;
  }
}

interface Message {
  sender: "user" | "bot";
  text: string;
  suggestedEvents?: CalendarEventSuggestion[];
  isWizardMessage?: boolean;
}

// Render bot messages: allow raw HTML (buttons), Markdown headings, math via KaTeX.
function renderMarkup(text: string) {
  if (!text) return null;
  const normalized = text.replace(/(^|\n)\*\s+/g, '$1- ');
  
  // Custom component overrides for ReactMarkdown to ensure lists and headings render correctly
  const components = {
    ul: (props: any) => <ul style={{ marginLeft: '1.25rem', listStyleType: 'disc' }} {...props} />,
    li: (props: any) => <li style={{ marginBottom: '0.25rem' }} {...props} />,
    ol: (props: any) => <ol style={{ marginLeft: '1.25rem', listStyleType: 'decimal' }} {...props} />,
    h1: (props: any) => <h1 style={{ fontSize: '1.875rem', fontWeight: 'bold', marginTop: '0.7rem', marginBottom: '0.5rem' }} {...props} />,
    h2: (props: any) => <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', marginTop: '0.575rem', marginBottom: '0.5rem' }} {...props} />,
    h3: (props: any) => <h3 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginTop: '0.45rem', marginBottom: '0.5rem' }} {...props} />,
    h4: (props: any) => <h4 style={{ fontSize: '1.125rem', fontWeight: 'bold', marginTop: '0.2rem', marginBottom: '0.5rem' }} {...props} />,
  };
  
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath, remarkGfm]}
      rehypePlugins={[rehypeKatex, rehypeRaw]}
      components={components}
    >
      {normalized}
    </ReactMarkdown>
  );
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

  const CONV_KEY = "studibot_conv_id";
  const newConvId = () =>
    (crypto as any)?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;

  const [convId, setConvId] = useState<string>(() => {
    const existing = localStorage.getItem(CONV_KEY);
    if (existing) return existing;
    const fresh = newConvId();
    localStorage.setItem(CONV_KEY, fresh);
    return fresh;
  });

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
        api_key: apiKey,

        // logging / session tracking
        conv_id: convId,
        client_ts: new Date().toISOString(),
      });
      // Replace the typing indicator (last message) with the real response
      // Only add response message if response text is provided
      if (res.data && res.data.response) {
        setMessages(prev => {
          const withoutTyping = prev.slice(0, -1); // drop last (typing)
          return [...withoutTyping, { sender: "bot", text: res.data.response, isWizardMessage: res.data.is_wizard_message }];
        });
      } else {
        // Remove typing indicator if no response text
        setMessages(prev => prev.slice(0, -1));
      }

      // If backend returned settings, save them to localStorage
      if (res.data && res.data.settings) {
        try {
          localStorage.setItem('reminder_settings', JSON.stringify(res.data.settings));
          console.log('Reminder settings saved:', res.data.settings);
        } catch (e) {
          console.error('Failed to save settings:', e);
        }
      }

      // If the backend returned suggested events, create a message with buttons
      if (res.data && res.data.suggested_events && res.data.suggested_events.length > 0) {
        setMessages(prev => [...prev, { 
          sender: "bot", 
          text: "Welche Termine soll ich zum Kalender hinzufügen?",
          suggestedEvents: res.data.suggested_events
        }]);
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
        {/* Always render Calendar to keep window.addCalendarEvent available, but hide when not selected */}
        <div className={`h-full ${selectedTab === "calendar" ? "" : "hidden"}`}>
          <Calendar />
        </div>

        {selectedTab === "chat" && (
          <div>
            {messages.map((m,i)=>{
              const botBgClass = m.sender === "bot" && m.isWizardMessage
                ? (darkMode ? "bg-blue-600 text-white" : "bg-blue-400 text-white")
                : (m.sender === "user" ? "bg-green-500 text-white" : darkMode ? "bg-gray-700 text-white" : "bg-gray-300 text-black");
              return (
              <div key={i} className={`flex mb-4 ${m.sender==="user"?"justify-end":"justify-start"}`}>
                <div className={`rounded-lg p-3 max-w-[60%] md:max-w-[50%] lg:max-w-[40%] ${botBgClass}`}>
                  {/* Render bot/user text. Support simple HTML or Markdown from the backend. */}
                  {m.sender === "bot" ? (
                    <>
                      {renderMarkup(m.text)}
                      {m.suggestedEvents && m.suggestedEvents.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {m.suggestedEvents.map((evt, idx) => {
                            const dateStr = new Date(evt.date).toLocaleDateString('de-DE', { year: 'numeric', month: 'long', day: 'numeric' });
                            return (
                              <button
                                key={idx}
                                onClick={() => window.addCalendarEvent(evt.date, evt.title)}
                                className="inline-block px-3 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors"
                                title="Zum Kalender hinzufügen"
                              >
                                {evt.title} ({dateStr})
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </>
                  ) : (
                    // Render user message as plain text to avoid accidental HTML rendering
                    <div>{m.text}</div>
                  )}
                </div>
              </div>
              );
            })}
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
