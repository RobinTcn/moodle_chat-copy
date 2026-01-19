import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { GoogleOAuthProvider, useGoogleLogin } from '@react-oauth/google';

interface CalendarEvent {
	id: string;
	date: string; // ISO date YYYY-MM-DD
	text: string;
	source?: 'local' | 'google'; // Track event source
}

interface GoogleUser {
	email: string;
	name: string;
	picture: string;
	accessToken?: string;
}

const STORAGE_KEY = 'calendar_events_v1';
const USER_STORAGE_KEY = 'google_user_v1';
const ACCESS_TOKEN_KEY = 'google_access_token_v1';
const REFRESH_TOKEN_KEY = 'google_refresh_token_v1';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
// Use the actual frontend origin as redirect_uri
const REDIRECT_URI = window.location.origin;
const CALENDAR_SCOPES = 'https://www.googleapis.com/auth/calendar.readonly';

function saveEvents(events: CalendarEvent[]) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(events));
	} catch (e) {
		// ignore
	}
}

function loadEvents(): CalendarEvent[] {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];
		return JSON.parse(raw) as CalendarEvent[];
	} catch (e) {
		return [];
	}
}

function saveUser(user: GoogleUser | null) {
	try {
		if (user) {
			localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
		} else {
			localStorage.removeItem(USER_STORAGE_KEY);
		}
	} catch (e) {
		// ignore
	}
}

function loadUser(): GoogleUser | null {
	try {
		const raw = localStorage.getItem(USER_STORAGE_KEY);
		if (!raw) return null;
		return JSON.parse(raw) as GoogleUser;
	} catch (e) {
		return null;
	}
}

function saveAccessToken(token: string | null) {
	try {
		if (token) {
			localStorage.setItem(ACCESS_TOKEN_KEY, token);
		} else {
			localStorage.removeItem(ACCESS_TOKEN_KEY);
		}
	} catch (e) {
		// ignore
	}
}

function loadAccessToken(): string | null {
	try {
		return localStorage.getItem(ACCESS_TOKEN_KEY);
	} catch (e) {
		return null;
	}
}

function saveRefreshToken(token: string | null) {
	try {
		if (token) {
			localStorage.setItem(REFRESH_TOKEN_KEY, token);
		} else {
			localStorage.removeItem(REFRESH_TOKEN_KEY);
		}
	} catch (e) {
		// ignore
	}
}

function loadRefreshToken(): string | null {
	try {
		return localStorage.getItem(REFRESH_TOKEN_KEY);
	} catch (e) {
		return null;
	}
}

function isoDateFromParts(year: number, monthIndex: number, day: number) {
	// monthIndex: 0-11
	const d = new Date(year, monthIndex, day);
	// Build YYYY-MM-DD
	const mm = String(d.getMonth() + 1).padStart(2, '0');
	const dd = String(d.getDate()).padStart(2, '0');
	return `${d.getFullYear()}-${mm}-${dd}`;
}

function formatIsoToDisplay(iso: string) {
	// expect YYYY-MM-DD -> return DD.MM.YYYY
	const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
	if (!m) return iso;
	return `${m[3]}.${m[2]}.${m[1]}`;
}

function CalendarContent() {
	// current displayed month (use first day of month)
	const [current, setCurrent] = useState(() => {
		const now = new Date();
		return new Date(now.getFullYear(), now.getMonth(), 1);
	});

	const [events, setEvents] = useState<CalendarEvent[]>(() => loadEvents());
	const [googleEvents, setGoogleEvents] = useState<CalendarEvent[]>([]);
	const [openDay, setOpenDay] = useState<string | null>(null);
	const [user, setUser] = useState<GoogleUser | null>(() => loadUser());
	const [accessToken, setAccessToken] = useState<string | null>(() => loadAccessToken());
	const [refreshToken, setRefreshToken] = useState<string | null>(() => loadRefreshToken());
	const [isLoadingGoogleEvents, setIsLoadingGoogleEvents] = useState(false);

	// add-event modal state (replaces window.prompt)
	const [addModalDay, setAddModalDay] = useState<string | null>(null);
	const [addModalText, setAddModalText] = useState<string>("");

	// edit-event modal state
	const [editingEventId, setEditingEventId] = useState<string | null>(null);
	const [editingEventText, setEditingEventText] = useState<string>("");

	// expose global helper so other parts of the app (e.g. chatbot handlers) can add events
	useEffect(() => {
		// define a function on window
		// eslint-disable-next-line @typescript-eslint/ban-ts-comment
		// @ts-ignore
		window.addCalendarEvent = (dateISO: string, text: string) => {
			// Check for duplicates: same date AND same title in both local and Google events
			const allEvents = [...events, ...googleEvents];
			const isDuplicate = allEvents.some(ev => ev.date === dateISO && ev.text === text);
			
			if (isDuplicate) {
				alert('Dieser Termin existiert bereits in deinem Kalender!');
				return;
			}
			
			// If user is logged in with Google, send to Google Calendar only
			if (user && accessToken) {
				console.log('User is logged in with Google, syncing event from chatbot to Google Calendar only');
				syncEventToGoogleCalendar(text, dateISO, accessToken);
			} else {
				// If not logged in, save locally only
				const ev: CalendarEvent = { id: String(Date.now()) + Math.random().toString(36).slice(2), date: dateISO, text };
				const next = [...loadEvents(), ev];
				saveEvents(next);
				setEvents(next);
			}
			
			alert('Termin hinzugefügt!');
		};

		return () => {
			// eslint-disable-next-line @typescript-eslint/ban-ts-comment
			// @ts-ignore
			delete window.addCalendarEvent;
		};
	}, [user, accessToken, events, googleEvents]);

	// Notification system: Check for upcoming deadlines
	const checkReminders = useCallback(() => {
		console.log('[Reminder Check] Starting reminder check...');

		// Only check if we have notification permission
		if (!('Notification' in window) || Notification.permission !== 'granted') {
			console.log('[Reminder Check] No notification permission');
			return;
		}

		// Load reminder settings
		let settings;
		try {
			const stored = localStorage.getItem('reminder_settings');
			if (!stored) {
				console.log('[Reminder Check] No settings configured yet');
				return;
			}
			settings = JSON.parse(stored);
			console.log('[Reminder Check] Settings loaded:', settings);
		} catch (e) {
			console.error('[Reminder Check] Failed to load reminder settings:', e);
			return;
		}

		const taskDays = settings.reminder_days_tasks || 1;
		const examDays = settings.reminder_days_exams || 7;
		console.log(`[Reminder Check] Task days: ${taskDays}, Exam days: ${examDays}`);

		// Get all events (local + Google)
		const allEvents = [...events, ...googleEvents];
		console.log(`[Reminder Check] Found ${allEvents.length} events total`);
		const today = new Date();
		today.setHours(0, 0, 0, 0);
		console.log(`[Reminder Check] Today is: ${today.toISOString()}`);

		// Track which reminders we've already shown (stored in localStorage)
		let shownReminders: string[] = [];
		try {
			const stored = localStorage.getItem('shown_reminders');
			if (stored) shownReminders = JSON.parse(stored);
		} catch (e) {
			// ignore
		}

		allEvents.forEach(ev => {
			console.log(`[Reminder Check] Checking event: "${ev.text}" on ${ev.date}`);
			const eventDate = new Date(ev.date);
			eventDate.setHours(0, 0, 0, 0);

			const diffTime = eventDate.getTime() - today.getTime();
			const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
			console.log(`[Reminder Check] Days until event: ${diffDays}`);

			// Skip if event is in the past
			if (diffDays < 0) {
				console.log(`[Reminder Check] Event is in the past, skipping`);
				return;
			}

			// Determine if it's an exam (contains keywords) or task
			const isExam = /klausur|prüfung|exam|test/i.test(ev.text);
			const reminderDays = isExam ? examDays : taskDays;
			console.log(`[Reminder Check] Is exam: ${isExam}, Reminder days: ${reminderDays}`);

			// Check if we should remind today
			if (diffDays === reminderDays || diffDays === 0) {
				console.log(`[Reminder Check] Should send reminder for this event!`);
				// Create unique ID for this reminder
				const reminderId = `${ev.date}_${ev.text}_${diffDays}`;

				// Skip if already shown
				if (shownReminders.includes(reminderId)) {
					console.log(`[Reminder Check] Reminder already shown: ${reminderId}`);
					return;
				}

				// Show notification
				let message;
				if (diffDays === 0) {
					message = `Heute: ${ev.text}`;
				} else if (diffDays === 1) {
					message = `Morgen: ${ev.text}`;
				} else {
					message = `In ${diffDays} Tagen: ${ev.text}`;
				}

				console.log(`[Reminder Check] Sending notification: "${message}"`);
				new Notification('StudiBot Erinnerung 📅', {
					body: message,
					icon: '/favicon.ico',
					badge: '/favicon.ico',
					requireInteraction: false
				});

				// Mark as shown
				shownReminders.push(reminderId);
				console.log(`[Reminder Check] Reminder sent and marked as shown`);
			} else {
				console.log(`[Reminder Check] Not the right day yet (need: ${reminderDays}, got: ${diffDays})`);
			}
		});

		console.log(`[Reminder Check] Total reminders shown: ${shownReminders.length}`);

		// Save shown reminders
		try {
			localStorage.setItem('shown_reminders', JSON.stringify(shownReminders));
		} catch (e) {
			// ignore
		}
	}, [events, googleEvents]);

	// Request notification permission on mount
	useEffect(() => {
		if ('Notification' in window && Notification.permission === 'default') {
			Notification.requestPermission().then(permission => {
				console.log('Notification permission:', permission);
			});
		}
	}, []);

	// Run reminders immediately and hourly
	useEffect(() => {
		checkReminders();
		const interval = setInterval(checkReminders, 60 * 60 * 1000);
		return () => clearInterval(interval);
	}, [checkReminders]);

	// helper to add an event from UI
	const addEvent = (dateISO: string, text: string) => {
		// If user is logged in with Google, send to Google Calendar only
		if (user && accessToken) {
			console.log('User is logged in with Google, syncing event to Google Calendar only');
			syncEventToGoogleCalendar(text, dateISO, accessToken);
		} else {
			// If not logged in, save locally only
			const ev: CalendarEvent = { id: String(Date.now()) + Math.random().toString(36).slice(2), date: dateISO, text };
			const next = [...events, ev];
			saveEvents(next);
			setEvents(next);
		}
	};

	const syncEventToGoogleCalendar = async (title: string, date: string, token: string) => {
		try {
			console.log('Syncing event to Google Calendar:', title, date);
			const response = await fetch(`${BACKEND_URL}/api/google/calendar/create`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					access_token: token,
					title: title,
					date: date,
				}),
			});

			const data = await response.json();
			
			if (!response.ok) {
				console.error('Backend error response:', response.status, data);
				throw new Error(data.message || 'Failed to sync event to Google Calendar');
			}
			
			if (data.success) {
				console.log('✓ Event synced to Google Calendar:', data.event_id);
				// Add the Google event to our display
				setGoogleEvents(prev => [...prev, data.event]);
			} else {
				console.error('Failed to sync:', data.message);
			}
		} catch (e) {
			console.error('Error syncing event to Google Calendar:', e);
			// Don't fail the local save, just warn the user
			console.warn('Event saved locally but could not sync to Google Calendar');
		}
	};

	const removeEvent = (id: string) => {
		// If it's a Google Calendar event
		if (id.startsWith('google-')) {
			if (!accessToken || !user) {
				alert('Du musst mit Google angemeldet sein, um Google Calendar-Events zu löschen.');
				return;
			}
			deleteGoogleEvent(id);
		} else {
			// Local event
			const next = events.filter(e => e.id !== id);
			saveEvents(next);
			setEvents(next);
		}
	};

	const deleteGoogleEvent = async (eventId: string) => {
		try {
			console.log('Deleting Google Calendar event:', eventId);
			const response = await fetch(`${BACKEND_URL}/api/google/calendar/delete`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					access_token: accessToken,
					event_id: eventId,
				}),
			});

			const data = await response.json();
			
			if (!response.ok) {
				console.error('Backend error response:', response.status, data);
				alert('Fehler beim Löschen des Events: ' + (data.message || 'Unbekannter Fehler'));
				return;
			}
			
			if (data.success) {
				console.log('✓ Google event deleted:', eventId);
				// Remove from googleEvents state
				setGoogleEvents(prev => prev.filter(e => e.id !== eventId));
			} else {
				alert('Fehler beim Löschen des Events: ' + data.message);
			}
		} catch (e) {
			console.error('Error deleting Google event:', e);
			alert('Fehler beim Löschen des Events');
		}
	};

	const startEditEvent = (event: CalendarEvent) => {
		setEditingEventId(event.id);
		setEditingEventText(event.text);
	};

	const saveEditEvent = async () => {
		if (!editingEventId || !editingEventText.trim()) return;

		// If it's a Google Calendar event
		if (editingEventId.startsWith('google-')) {
			if (!accessToken || !user) {
				alert('Du musst mit Google angemeldet sein, um Google Calendar-Events zu bearbeiten.');
				return;
			}
			
			// Find the event to get its date
			const event = googleEvents.find(e => e.id === editingEventId);
			if (!event) return;

			try {
				console.log('Updating Google Calendar event:', editingEventId);
				const response = await fetch(`${BACKEND_URL}/api/google/calendar/update`, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/json',
					},
					body: JSON.stringify({
						access_token: accessToken,
						event_id: editingEventId,
						title: editingEventText,
						date: event.date,
					}),
				});

				const data = await response.json();
				
				if (!response.ok) {
					console.error('Backend error response:', response.status, data);
					alert('Fehler beim Aktualisieren des Events: ' + (data.message || 'Unbekannter Fehler'));
					return;
				}
				
				if (data.success) {
					console.log('✓ Google event updated:', editingEventId);
					// Update googleEvents state
					setGoogleEvents(prev => prev.map(e => 
						e.id === editingEventId 
							? { ...e, text: editingEventText } 
							: e
					));
				}
			} catch (e) {
				console.error('Error updating Google event:', e);
				alert('Fehler beim Aktualisieren des Events');
			}
		} else {
			// Local event
			const next = events.map(e => 
				e.id === editingEventId 
					? { ...e, text: editingEventText } 
					: e
			);
			saveEvents(next);
			setEvents(next);
		}

		setEditingEventId(null);
		setEditingEventText("");
	};

	const handleGoogleSuccess = async (codeResponse: any) => {
		try {
			console.log('OAuth code response received:', codeResponse);
			const code = codeResponse.code;
			
			if (!code) {
				throw new Error('No authorization code received');
			}
			
			console.log('Exchanging code for tokens via backend...');
			// Exchange code for tokens via backend
			const response = await fetch(`${BACKEND_URL}/api/google/oauth/callback`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					code: code,
					redirect_uri: REDIRECT_URI,
				}),
			});

			console.log('Backend response status:', response.status);
			
			if (!response.ok) {
				const errorText = await response.text();
				console.error('Backend error:', errorText);
				throw new Error(`Failed to exchange code for token: ${response.status}`);
			}

			const data = await response.json();
			console.log('Backend response data:', data);
			
			if (!data.success) {
				throw new Error(data.message || 'OAuth failed');
			}

			const userData: GoogleUser = {
				email: data.user.email,
				name: data.user.name,
				picture: data.user.picture,
				accessToken: data.access_token
			};
			
			setUser(userData);
			saveUser(userData);
			setAccessToken(data.access_token);
			saveAccessToken(data.access_token);
			
			// Save refresh token if provided
			if (data.refresh_token) {
				setRefreshToken(data.refresh_token);
				saveRefreshToken(data.refresh_token);
			}

			console.log('Fetching calendar events...');
			// Fetch calendar events
			await fetchGoogleCalendarEvents(data.access_token);
		} catch (e) {
			console.error('Failed to handle Google login:', e);
			const errorMessage = e instanceof Error ? e.message : 'Unknown error';
			alert(`Google-Anmeldung fehlgeschlagen: ${errorMessage}\n\nBitte überprüfen Sie die Konsole für Details.`);
		}
	};

	const fetchGoogleCalendarEvents = async (token: string) => {
		setIsLoadingGoogleEvents(true);
		try {
			// Get events for current month
			const startOfMonth = new Date(current.getFullYear(), current.getMonth(), 1);
			const endOfMonth = new Date(current.getFullYear(), current.getMonth() + 1, 0, 23, 59, 59);

			const response = await fetch(`${BACKEND_URL}/api/google/calendar/events`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					access_token: token,
					time_min: startOfMonth.toISOString(),
					time_max: endOfMonth.toISOString(),
				}),
			});

			if (!response.ok) {
				throw new Error('Failed to fetch calendar events');
			}

			const data = await response.json();
			
			if (data.success) {
				setGoogleEvents(data.events);
			}
		} catch (e) {
			console.error('Failed to fetch Google Calendar events:', e);
			// Try to refresh token if fetch fails
			if (refreshToken) {
				await tryRefreshToken();
			}
		} finally {
			setIsLoadingGoogleEvents(false);
		}
	};

	const tryRefreshToken = async () => {
		if (!refreshToken) return;
		
		try {
			const response = await fetch(`${BACKEND_URL}/api/google/oauth/refresh`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
				},
				body: JSON.stringify({
					refresh_token: refreshToken,
				}),
			});

			if (!response.ok) {
				throw new Error('Failed to refresh token');
			}

			const data = await response.json();
			
			if (data.success) {
				setAccessToken(data.access_token);
				saveAccessToken(data.access_token);
				// Try fetching events again with new token
				await fetchGoogleCalendarEvents(data.access_token);
			}
		} catch (e) {
			console.error('Failed to refresh token:', e);
			// If refresh fails, clear tokens and log out
			handleLogout();
		}
	};

	const handleLogout = () => {
		setUser(null);
		saveUser(null);
		setAccessToken(null);
		saveAccessToken(null);
		setRefreshToken(null);
		saveRefreshToken(null);
		setGoogleEvents([]);
	};

	// Initialize Google login with proper scopes
	const login = useGoogleLogin({
		onSuccess: handleGoogleSuccess,
		onError: (error) => console.error('Login Failed:', error),
		scope: 'https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile',
		flow: 'auth-code', // Use authorization code flow for backend exchange
	});

	const year = current.getFullYear();
	const monthIndex = current.getMonth();

	const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();

	const monthName = current.toLocaleString(undefined, { month: 'long' });

	// Refetch Google Calendar events when month changes
	useEffect(() => {
		if (accessToken && user) {
			fetchGoogleCalendarEvents(accessToken);
		}
	}, [current, accessToken, user]);

	// Merge local and Google events
	const allEvents = useMemo(() => {
		return [...events, ...googleEvents];
	}, [events, googleEvents]);

	// grouped events by date
	const eventsByDate = useMemo(() => {
		const map: Record<string, CalendarEvent[]> = {};
		for (const e of allEvents) {
			if (!map[e.date]) map[e.date] = [];
			map[e.date].push(e);
		}
		return map;
	}, [allEvents]);

	const prevMonth = () => setCurrent(c => new Date(c.getFullYear(), c.getMonth() - 1, 1));
	const nextMonth = () => setCurrent(c => new Date(c.getFullYear(), c.getMonth() + 1, 1));

	const openAddPrompt = (d: string) => {
		setAddModalDay(d);
		setAddModalText("");
	};

	// render day cells (start with Mon..Sun header)
	const dayNames = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

	// adjust first day index so Monday=0 .. Sunday=6
	const firstDayIndex = (new Date(year, monthIndex, 1).getDay() + 6) % 7; // shift so Mon=0

	const cells: Array<null | { day: number; iso: string }> = [];
	// leading empty cells for days before the 1st
	for (let i = 0; i < firstDayIndex; i++) cells.push(null);
	for (let d = 1; d <= daysInMonth; d++) {
		cells.push({ day: d, iso: isoDateFromParts(year, monthIndex, d) });
	}

		return (
			<>
			<div className="max-w-4xl mx-auto h-full flex flex-col">
				{/* Google Login / User Profile Section */}
				<div className="mb-4 flex items-center justify-between bg-white p-3 rounded-lg shadow-sm">
					{user ? (
						<div className="flex items-center gap-3 w-full">
							<img src={user.picture} alt={user.name} className="w-10 h-10 rounded-full" />
							<div className="flex-1">
								<div className="font-medium">{user.name}</div>
								<div className="text-sm text-gray-600">
									{user.email}
									{isLoadingGoogleEvents && <span className="ml-2 text-blue-500">Lade Kalender...</span>}
								</div>
							</div>
							<button 
								onClick={handleLogout}
								className="px-4 py-2 text-sm bg-red-500 text-white rounded hover:bg-red-600"
							>
								Abmelden
							</button>
						</div>
					) : (
						<div className="w-full flex items-center justify-between">
							<div className="text-sm text-gray-600">Mit Google anmelden, um Ihren Kalender zu synchronisieren</div>
							<button
								onClick={() => login()}
								className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 rounded hover:bg-gray-50 text-sm font-medium"
							>
								<svg width="18" height="18" viewBox="0 0 18 18" xmlns="http://www.w3.org/2000/svg">
									<path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"/>
									<path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z"/>
									<path fill="#FBBC05" d="M3.964 10.707c-.18-.54-.282-1.117-.282-1.707s.102-1.167.282-1.707V4.961H.957C.347 6.175 0 7.55 0 9s.348 2.825.957 4.039l3.007-2.332z"/>
									<path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
								</svg>
								Mit Google anmelden
							</button>
						</div>
					)}
				</div>

				<div className="flex items-center justify-between mb-4">
					<div className="relative w-full flex items-center justify-center">
						<div className="absolute left-0">
							<button onClick={prevMonth} aria-label="Vorheriger Monat" className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300 ml-1">
								<svg className="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
									<path d="M12 16 L6 10 L12 4" />
								</svg>
							</button>
						</div>
						<div className="text-lg font-medium text-center px-4">{monthName} {year}</div>
						<div className="absolute right-0 flex gap-2">
							<button onClick={() => checkReminders()} aria-label="Erinnerungen jetzt senden" className="px-3 py-1 rounded bg-blue-500 text-white hover:bg-blue-600">
								Jetzt erinnern
							</button>
							<button onClick={nextMonth} aria-label="Nächster Monat" className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300">
								<svg className="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
									<path d="M8 16 L14 10 L8 4" />
								</svg>
							</button>
						</div>
					</div>
				</div>

					<div className="grid grid-cols-7 gap-1 text-center">
						{dayNames.map(dn => (
							<div key={dn} className="text-sm font-semibold text-gray-600">{dn}</div>
						))}
					</div>

					{/* day cells: stretch to fill remaining vertical space */}
					<div className="grid grid-cols-7 auto-rows-fr gap-1 text-center flex-1">
						{cells.map((c, idx) => {
							if (!c) return <div key={idx} className="h-full p-1 border border-transparent" />;
							const evs = eventsByDate[c.iso] || [];
							return (
								<div
									key={c.iso}
									onClick={() => setOpenDay(c.iso)}
									className="h-full p-2 border rounded-lg bg-white flex flex-col justify-between cursor-pointer"
								>
									<div className="flex items-start justify-between">
										<div className="text-sm font-medium">{c.day}</div>
										<div className="flex items-center gap-1">
											<button
												title="Hinzufügen"
												onClick={(e) => { e.stopPropagation(); openAddPrompt(c.iso); }}
												className="text-green-600 px-1 py-0.5 rounded hover:bg-green-50"
											>
												+
											</button>
										</div>
									</div>

									<div className="mt-2 text-xs text-left space-y-1">
										{evs.slice(0, 3).map(e => (
											<div key={e.id} className="flex items-center justify-between gap-2">
												<div className="truncate flex items-center gap-1">
													{e.source === 'google' ? (
														<span className="text-blue-500" title="Google Calendar">📅</span>
													) : (
														<span>•</span>
													)}
													{e.text}
												</div>
												{e.source !== 'google' && (
													<button title="Entfernen" onClick={(ev) => { ev.stopPropagation(); removeEvent(e.id); }} className="text-red-500 ml-2">✕</button>
												)}
											</div>
										))}
										{evs.length > 3 && <div className="text-gray-400 text-xs">+{evs.length - 3} mehr</div>}
									</div>
								</div>
							);
						})}
					</div>

				{/* simple modal / drawer for day details */}
				{openDay && (
					<div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center p-4 z-50">
						<div className="bg-white rounded-lg max-w-md w-full p-4">
									<div className="flex items-center justify-between mb-2">
										<div className="font-medium">Einträge am {openDay ? formatIsoToDisplay(openDay) : ''}</div>
										<button onClick={() => setOpenDay(null)} className="text-gray-500">Schließen</button>
									</div>
							<div className="space-y-2 max-h-56 overflow-auto">
								{(eventsByDate[openDay] || []).map(e => (
									<div key={e.id} className="flex items-start justify-between gap-2 p-2 border rounded">
										<div className="flex items-center gap-2 flex-1 min-w-0">
											{e.source === 'google' && (
												<span className="text-blue-500 text-sm" title="Google Calendar">📅</span>
											)}
											<span className="truncate">{e.text}</span>
										</div>
										<div className="flex gap-1 flex-shrink-0">
											<button 
												onClick={() => startEditEvent(e)} 
												className="text-sm text-blue-500 hover:text-blue-700"
												title="Bearbeiten"
											>
												✏️
											</button>
											<button 
												onClick={() => removeEvent(e.id)} 
												className="text-sm text-red-500 hover:text-red-700"
												title="Löschen"
											>
												✕
											</button>
										</div>
									</div>
								))}
								{(eventsByDate[openDay] || []).length === 0 && <div className="text-gray-500">Keine Einträge.</div>}
							</div>
							<div className="mt-3 flex gap-2">
								<button onClick={() => { if (openDay) { setAddModalDay(openDay); setAddModalText(""); } }} className="bg-green-500 text-white px-3 py-1 rounded">Neuen Eintrag</button>
								<button onClick={() => setOpenDay(null)} className="px-3 py-1 rounded border">Fertig</button>
							</div>
						</div>
					</div>
				)}
			</div>

			{/* Add-event modal (inline) */}
			{addModalDay && (
				<div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center p-4 z-50">
					<div className="bg-white rounded-lg max-w-md w-full p-4">
						<div className="flex items-center justify-between mb-2">
							<div className="font-medium">Neuen Eintrag für {formatIsoToDisplay(addModalDay as string)}</div>
							<button onClick={() => setAddModalDay(null)} className="text-gray-500">Abbrechen</button>
						</div>
						<div>
							<textarea
								value={addModalText}
								onChange={(e) => setAddModalText(e.target.value)}
								rows={4}
								className="w-full border rounded p-2"
								placeholder="Beschreibung eingeben..."
							/>
						</div>
						<div className="mt-3 flex justify-end gap-2">
							<button onClick={() => setAddModalDay(null)} className="px-3 py-1 rounded border">Abbrechen</button>
							<button
								onClick={() => {
								if (addModalDay && addModalText.trim()) {
									addEvent(addModalDay, addModalText.trim());
								}
								setAddModalDay(null);
								setAddModalText("");
							}}
							className="bg-green-500 text-white px-3 py-1 rounded"
							>
								Speichern
							</button>
						</div>
					</div>
				</div>
			)}

			{/* Edit-event modal */}
			{editingEventId && (
				<div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center p-4 z-50">
					<div className="bg-white rounded-lg max-w-md w-full p-4">
						<div className="flex items-center justify-between mb-2">
							<div className="font-medium">Eintrag bearbeiten</div>
							<button onClick={() => { setEditingEventId(null); setEditingEventText(""); }} className="text-gray-500">Abbrechen</button>
						</div>
						<div>
							<textarea
								value={editingEventText}
								onChange={(e) => setEditingEventText(e.target.value)}
								rows={4}
								className="w-full border rounded p-2"
								placeholder="Beschreibung eingeben..."
							/>
						</div>
						<div className="mt-3 flex justify-end gap-2">
							<button onClick={() => { setEditingEventId(null); setEditingEventText(""); }} className="px-3 py-1 rounded border">Abbrechen</button>
							<button
								onClick={() => saveEditEvent()}
								className="bg-blue-500 text-white px-3 py-1 rounded"
							>
								Speichern
							</button>
						</div>
					</div>
				</div>
			)}
			</>
		);
	}

export default function Calendar() {
	return (
		<GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
			<CalendarContent />
		</GoogleOAuthProvider>
	);
}
