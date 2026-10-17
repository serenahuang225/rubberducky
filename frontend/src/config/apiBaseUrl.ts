import Constants from 'expo-constants';
import { Platform } from 'react-native';

export const API_PORT = 3100;

type ResolveOptions = {
  explicit?: string;
  platform: string;
  hostUri?: string | null;
};

// Expo Go serves the bundle from the Mac's LAN address (hostUri "192.168.x.y:8081"), so the
// iPad reaches the API on the same host. Web and simulators use loopback.
export function resolveApiBaseUrl({ explicit, platform, hostUri }: ResolveOptions): string {
  const configured = explicit?.trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }
  if (platform !== 'web' && hostUri) {
    const host = hostUri.split('/')[0].replace(/:\d+$/, '');
    if (host) {
      return `http://${host}:${API_PORT}`;
    }
  }
  return `http://127.0.0.1:${API_PORT}`;
}

export function getApiBaseUrl(): string {
  return resolveApiBaseUrl({
    explicit: process.env.EXPO_PUBLIC_API_BASE_URL,
    platform: Platform.OS,
    hostUri: Constants.expoConfig?.hostUri ?? null,
  });
}
