export interface CalendarEventSuggestion {
  date: string;  // ISO format: YYYY-MM-DD
  title: string;
}

export interface ReminderSettings {
  reminder_days_tasks: number;
  reminder_days_exams: number;
}

export interface ChatResponse {
  response: string;
  // optional: basename of the saved ICS file on the backend (e.g. debug_ics_response_... .ics)
  ics_filename?: string;
  // optional: raw ICS content
  ics?: string;
  // optional: suggested calendar events to add
  suggested_events?: CalendarEventSuggestion[];
  // optional: reminder settings configured by user
  settings?: ReminderSettings;
  // optional: wizard state (true if exam preparation wizard is active)
  wizard_active?: boolean;
  // optional: whether this message was sent by the wizard
  is_wizard_message?: boolean;
}
