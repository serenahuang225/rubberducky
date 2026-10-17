import { resolveApiBaseUrl } from './apiBaseUrl';

describe('resolveApiBaseUrl', () => {
  it('prefers an explicit public base URL without a trailing slash', () => {
    expect(resolveApiBaseUrl({ explicit: 'http://10.0.0.5:3100/', platform: 'ios' })).toBe(
      'http://10.0.0.5:3100',
    );
  });

  it('uses the Expo LAN host for native clients', () => {
    expect(resolveApiBaseUrl({ platform: 'ios', hostUri: '192.168.1.20:8081' })).toBe(
      'http://192.168.1.20:3100',
    );
  });

  it('uses loopback on web even when a host URI exists', () => {
    expect(resolveApiBaseUrl({ platform: 'web', hostUri: '192.168.1.20:8081' })).toBe(
      'http://127.0.0.1:3100',
    );
  });

  it('falls back to loopback without a host URI', () => {
    expect(resolveApiBaseUrl({ platform: 'ios', hostUri: null })).toBe('http://127.0.0.1:3100');
  });
});
