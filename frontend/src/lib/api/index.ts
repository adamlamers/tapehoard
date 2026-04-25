import { client } from './client.gen';

// In production, we use relative paths because the frontend is served by the backend.
// In development, we can override this via an environment variable.
const BASE_URL = import.meta.env.VITE_API_URL || '';

client.setConfig({
    baseUrl: BASE_URL,
});

export * from './client.gen';
export * from './sdk.gen';
export * from './types.gen';
