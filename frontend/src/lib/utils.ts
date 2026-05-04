import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

/**
 * Ensures a date string from the backend is correctly parsed as UTC
 * even if the 'Z' suffix is missing.
 */
export function parseUTCDate(dateStr: string | null | undefined): Date | null {
    if (!dateStr) return null;
    // If it doesn't end with Z and doesn't contain a timezone offset, append Z
    const normalized = (dateStr.endsWith('Z') || dateStr.includes('+'))
        ? dateStr
        : `${dateStr}Z`;
    return new Date(normalized);
}

/**
 * Formats a UTC date string into a local human-readable string.
 */
export function formatLocalTime(dateStr: string | null | undefined): string {
    const date = parseUTCDate(dateStr);
    if (!date) return "--:--";
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function formatLocalDate(dateStr: string | null | undefined): string {
    const date = parseUTCDate(dateStr);
    if (!date) return "--/--/----";
    return date.toLocaleDateString();
}

export function formatLocalDateTime(dateStr: string | null | undefined): string {
    const date = parseUTCDate(dateStr);
    if (!date) return "--";
    return date.toLocaleString();
}

/**
 * Formats a byte count into a human-readable string (KB, MB, GB, TB).
 * (MEDIUM #28 — consolidated from 5+ duplicate implementations)
 */
export function formatSize(bytes: number | null | undefined): string {
    if (bytes === 0) return "0 B";
    if (!bytes) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let unitIndex = 0;
    let size = bytes;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}
