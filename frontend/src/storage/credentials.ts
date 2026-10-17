/**
 * Durable on-device pairing credential storage.
 *
 * The access token never leaves the device except as a bearer header to the local server.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';

const CREDENTIALS_KEY = 'rubberducky.credentials.v1';
const THEME_KEY = 'rubberducky.board-theme.v1';

export type StoredCredentials = {
  accessToken: string;
  learnerId: string;
  displayName: string;
};

export async function loadCredentials(): Promise<StoredCredentials | null> {
  const raw = await AsyncStorage.getItem(CREDENTIALS_KEY);
  if (raw === null) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<StoredCredentials>;
    if (
      typeof parsed.accessToken === 'string' &&
      typeof parsed.learnerId === 'string' &&
      typeof parsed.displayName === 'string'
    ) {
      return {
        accessToken: parsed.accessToken,
        learnerId: parsed.learnerId,
        displayName: parsed.displayName,
      };
    }
    return null;
  } catch {
    return null;
  }
}

export async function saveCredentials(credentials: StoredCredentials): Promise<void> {
  await AsyncStorage.setItem(CREDENTIALS_KEY, JSON.stringify(credentials));
}

export async function clearCredentials(): Promise<void> {
  await AsyncStorage.removeItem(CREDENTIALS_KEY);
}

export async function loadThemeName(): Promise<string | null> {
  return AsyncStorage.getItem(THEME_KEY);
}

export async function saveThemeName(name: string): Promise<void> {
  await AsyncStorage.setItem(THEME_KEY, name);
}
