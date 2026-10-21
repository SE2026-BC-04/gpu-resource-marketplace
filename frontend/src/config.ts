const configuredApiUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const apiUrl = new URL(configuredApiUrl);

if (!["http:", "https:"].includes(apiUrl.protocol) || apiUrl.username || apiUrl.password) {
  throw new Error("VITE_API_BASE_URL must be an HTTP(S) URL without credentials");
}

export const config = { apiBaseUrl: apiUrl.toString().replace(/\/$/, "") };
