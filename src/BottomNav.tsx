import React from 'react';

type Tab = 'calendar' | 'chat' | 'settings';

interface Props {
  selectedTab: Tab;
  onSelect: (t: Tab) => void;
}

function CalendarIcon({ active }: { active?: boolean }) {
  return (
    <svg className={`w-6 h-6 ${active ? 'text-green-600' : 'text-gray-600'}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
    </svg>
  );
}

function ChatIcon({ active }: { active?: boolean }) {
  return (
    <svg className={`w-6 h-6 ${active ? 'text-green-600' : 'text-gray-600'}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function SettingsIcon({ active }: { active?: boolean }) {
  return (
    <svg className={`w-6 h-6 ${active ? 'text-green-600' : 'text-gray-600'}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82L4.21 4.21A2 2 0 0 1 7 1.38l.06.06a1.65 1.65 0 0 0 1.82.33H9A1.65 1.65 0 0 0 11 2.8V3a2 2 0 0 1 4 0v.09c.12.6.5 1.07 1 1.51h.1a1.65 1.65 0 0 0 1.82-.33l.06-.06A2 2 0 0 1 20.62 7l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.45.5.89.88 1.51 1H21a2 2 0 0 1 0 4h-.09c-.62.12-1.06.5-1.51 1z" />
    </svg>
  );
}

export default function BottomNav({ selectedTab, onSelect }: Props) {
  return (
    <nav className="fixed left-0 right-0 bottom-0 bg-white border-t">
      <div className="max-w-4xl mx-auto grid grid-cols-3">
        <button
          aria-label="Kalender"
          aria-pressed={selectedTab === 'calendar'}
          onClick={() => onSelect('calendar')}
          className={`flex flex-col items-center justify-center p-2 py-3 focus:outline-none ${selectedTab === 'calendar' ? 'text-green-600' : 'text-gray-600'}`}
        >
          <CalendarIcon active={selectedTab === 'calendar'} />
          <span className="text-xs mt-1 hidden md:block">Kalender</span>
        </button>

        <button
          aria-label="Chat"
          aria-pressed={selectedTab === 'chat'}
          onClick={() => onSelect('chat')}
          className={`flex flex-col items-center justify-center p-2 py-3 focus:outline-none ${selectedTab === 'chat' ? 'text-green-600' : 'text-gray-600'}`}
        >
          <ChatIcon active={selectedTab === 'chat'} />
          <span className="text-xs mt-1 hidden md:block">Chat</span>
        </button>

        <button
          aria-label="Einstellungen"
          aria-pressed={selectedTab === 'settings'}
          onClick={() => onSelect('settings')}
          className={`flex flex-col items-center justify-center p-2 py-3 focus:outline-none ${selectedTab === 'settings' ? 'text-green-600' : 'text-gray-600'}`}
        >
          <SettingsIcon active={selectedTab === 'settings'} />
          <span className="text-xs mt-1 hidden md:block">Einstellungen</span>
        </button>
      </div>
    </nav>
  );
}
