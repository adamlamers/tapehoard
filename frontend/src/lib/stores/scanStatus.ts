import { writable } from 'svelte/store';
import type { ScanStatusSchema } from '$lib/api';

export const scanStatus = writable<ScanStatusSchema | null>(null);
