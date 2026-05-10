import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const SUPPORT_KEY = 'tapehoard_support_hidden';

function createSupportStore() {
	const initial = browser ? localStorage.getItem(SUPPORT_KEY) !== 'true' : true;
	const { subscribe, set } = writable(initial);
	return {
		subscribe,
		set: (value: boolean) => {
			if (browser) localStorage.setItem(SUPPORT_KEY, String(!value));
			set(value);
		}
	};
}

export const showSupportButton = createSupportStore();
