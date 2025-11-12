// src/App.tsx
import React, { useState, useRef, useEffect } from 'react';
import axios from 'axios';
import { ChatResponse } from './ChatResponse';

interface Message {
  sender: "user" | "bot";
  text: string;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
      <div className="p-4 bg-white border-b flex gap-2">
        <input type="text" placeholder="Benutzername" className="border rounded-lg p-2 flex-1" value={username} onChange={e=>setUsername(e.target.value)} />
        <input type="password" placeholder="Passwort" className="border rounded-lg p-2 flex-1" value={password} onChange={e=>setPassword(e.target.value)} />
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {messages.map((m,i)=>(
          <div key={i} className={`flex mb-2 ${m.sender==="user"?"justify-end":"justify-start"}`}>
            <div className={`rounded-lg p-3 max-w-xs ${m.sender==="user"?"bg-green-500 text-white":"bg-gray-300 text-black"}`}>
              {m.text}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <div className="flex p-4 bg-white border-t">
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
  );
}

export default App;
