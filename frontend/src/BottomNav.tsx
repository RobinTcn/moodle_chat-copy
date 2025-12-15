import React from 'react';
import { IoCalendarClearOutline } from 'react-icons/io5';
import { IoChatbubbleOutline } from 'react-icons/io5';
import { IoSettingsOutline } from 'react-icons/io5';

type Tab = 'calendar' | 'chat' | 'settings';

interface Props {
  selectedTab: Tab;
  onSelect: (t: Tab) => void;
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
          <IoCalendarClearOutline className="w-6 h-6" aria-hidden />
          <span className="text-xs mt-1 hidden md:block">Kalender</span>
        </button>

        <button
          aria-label="Chat"
          aria-pressed={selectedTab === 'chat'}
          onClick={() => onSelect('chat')}
          className={`flex flex-col items-center justify-center p-2 py-3 focus:outline-none ${selectedTab === 'chat' ? 'text-green-600' : 'text-gray-600'}`}
        >
          <IoChatbubbleOutline className="w-6 h-6" aria-hidden />
          <span className="text-xs mt-1 hidden md:block">Chat</span>
        </button>

        <button
          aria-label="Einstellungen"
          aria-pressed={selectedTab === 'settings'}
          onClick={() => onSelect('settings')}
          className={`flex flex-col items-center justify-center p-2 py-3 focus:outline-none ${selectedTab === 'settings' ? 'text-green-600' : 'text-gray-600'}`}
        >
          <IoSettingsOutline className="w-6 h-6" aria-hidden />
          <span className="text-xs mt-1 hidden md:block">Einstellungen</span>
        </button>
      </div>
    </nav>
  );
}
