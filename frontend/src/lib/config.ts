/**
 * Shared configuration constants for the TapeHoard frontend.
 * (LOW #34 — centralises magic-number polling intervals)
 */

/** Polling interval for scan-status and job-detail overlays (ms) */
export const POLL_FAST = 2000;

/** Polling interval for inventory media list and filesystem status (ms) */
export const POLL_SLOW = 3000;
