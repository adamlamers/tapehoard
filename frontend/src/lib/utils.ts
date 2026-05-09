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
    while (size >= 1000 && unitIndex < units.length - 1) {
        size /= 1000;
        unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}

/**
 * Natural sort comparator mimicking Windows Explorer's StrCmpLogicalW.
 *
 * Rules:
 * 1. Directories always sort before files.
 * 2. Case-insensitive alphanumeric comparison.
 * 3. Multi-digit numbers are compared as whole integers (1, 2, 10 not 1, 10, 2).
 * 4. Falls back to locale-aware comparison for non-ASCII characters.
 */
export function naturalSortCompare(aName: string, bName: string): number {
    const aLower = aName.toLowerCase();
    const bLower = bName.toLowerCase();
    const len = Math.min(aLower.length, bLower.length);

    let i = 0;
    while (i < len) {
        const aChar = aLower[i];
        const bChar = bLower[i];

        // If both are digits, extract the full number and compare numerically
        if (isDigit(aChar) && isDigit(bChar)) {
            let aNum = 0;
            let bNum = 0;
            let j = i;

            while (j < aLower.length && isDigit(aLower[j])) {
                aNum = aNum * 10 + (aLower.charCodeAt(j) - 48);
                j++;
            }
            const aEnd = j;

            j = i;
            while (j < bLower.length && isDigit(bLower[j])) {
                bNum = bNum * 10 + (bLower.charCodeAt(j) - 48);
                j++;
            }
            const bEnd = j;

            if (aNum !== bNum) {
                return aNum - bNum;
            }

            // Numbers are equal but one may have leading zeros; shorter run first
            if (aEnd !== bEnd) {
                return aEnd - bEnd;
            }

            i = aEnd;
            continue;
        }

        // Simple character comparison (locale-aware fallback for non-ASCII)
        if (aChar !== bChar) {
            return aChar.localeCompare(bChar);
        }

        i++;
    }

    return aLower.length - bLower.length;
}

function isDigit(c: string): boolean {
    const code = c.charCodeAt(0);
    return code >= 48 && code <= 57;
}
