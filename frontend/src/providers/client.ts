import { Client } from "@langchain/langgraph-sdk";

export function resolveApiUrl(apiUrl: string): string {
  const raw = (apiUrl || "").trim().replace(/\/+$/, "");
  if (!raw) return raw;
  if (/^https?:\/\//i.test(raw)) return raw;
  if (raw.startsWith("/")) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}${raw}`;
    }
  }
  return raw;
}

export function createClient(
  apiUrl: string,
  apiKey: string | undefined,
  authScheme: string | undefined,
) {
  return new Client({
    apiKey,
    apiUrl: resolveApiUrl(apiUrl),
    ...(authScheme && {
      defaultHeaders: {
        "X-Auth-Scheme": authScheme,
      },
    }),
  });
}
