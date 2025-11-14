import React, { useEffect, useMemo, useState } from 'react';

interface CalendarEvent {
	id: string;
	date: string; // ISO date YYYY-MM-DD
	text: string;
}

const STORAGE_KEY = 'calendar_events_v1';

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

export default function Calendar() {
	// current displayed month (use first day of month)
	const [current, setCurrent] = useState(() => {
		const now = new Date();
		return new Date(now.getFullYear(), now.getMonth(), 1);
	});

	const [events, setEvents] = useState<CalendarEvent[]>(() => loadEvents());
	const [openDay, setOpenDay] = useState<string | null>(null);

	// add-event modal state (replaces window.prompt)
	const [addModalDay, setAddModalDay] = useState<string | null>(null);
	const [addModalText, setAddModalText] = useState<string>("");

	// expose global helper so other parts of the app (e.g. chatbot handlers) can add events
	useEffect(() => {
		// define a function on window
		// eslint-disable-next-line @typescript-eslint/ban-ts-comment
		// @ts-ignore
		window.addCalendarEvent = (dateISO: string, text: string) => {
			const ev: CalendarEvent = { id: String(Date.now()) + Math.random().toString(36).slice(2), date: dateISO, text };
			const next = [...loadEvents(), ev];
			saveEvents(next);
			setEvents(next);
		};

		return () => {
			// eslint-disable-next-line @typescript-eslint/ban-ts-comment
			// @ts-ignore
			delete window.addCalendarEvent;
		};
	}, []);

	// helper to add an event from UI
	const addEvent = (dateISO: string, text: string) => {
		const ev: CalendarEvent = { id: String(Date.now()) + Math.random().toString(36).slice(2), date: dateISO, text };
		const next = [...events, ev];
		saveEvents(next);
		setEvents(next);
	};

	const removeEvent = (id: string) => {
		const next = events.filter(e => e.id !== id);
		saveEvents(next);
		setEvents(next);
	};

	const year = current.getFullYear();
	const monthIndex = current.getMonth();

	const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();

	const monthName = current.toLocaleString(undefined, { month: 'long' });

	// grouped events by date
	const eventsByDate = useMemo(() => {
		const map: Record<string, CalendarEvent[]> = {};
		for (const e of events) {
			if (!map[e.date]) map[e.date] = [];
			map[e.date].push(e);
		}
		return map;
	}, [events]);

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
						<div className="absolute right-0">
							<button onClick={nextMonth} aria-label="Nächster Monat" className="px-3 py-1 rounded bg-gray-200 hover:bg-gray-300 mr-1">
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
												<div className="truncate">• {e.text}</div>
												<button title="Entfernen" onClick={(ev) => { ev.stopPropagation(); removeEvent(e.id); }} className="text-red-500 ml-2">✕</button>
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
										<div>{e.text}</div>
										<div className="flex flex-col gap-1">
											<button onClick={() => { removeEvent(e.id); }} className="text-sm text-red-500">Löschen</button>
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
			</>
		);
	}
