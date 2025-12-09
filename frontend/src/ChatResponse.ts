export interface ChatResponse {
  response: string;
  // optional: basename of the saved ICS file on the backend (e.g. debug_ics_response_... .ics)
  ics_filename?: string;
  // optional: raw ICS content
  ics?: string;
}
