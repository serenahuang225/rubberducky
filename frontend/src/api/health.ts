import { z } from 'zod';

export const appHealthSchema = z.object({
  schema_version: z.literal('health.v1'),
  status: z.literal('ok'),
  service: z.literal('rubberducky-api'),
  version: z.string(),
  time_utc: z.string(),
});

export const modelReadinessSchema = z.object({
  schema_version: z.literal('model-readiness.v1'),
  provider: z.enum(['mock', 'transformers', 'endpoint', 'claude']),
  state: z.enum(['ready', 'not_loaded', 'disabled', 'unverified']),
  ready: z.boolean(),
  is_mock: z.boolean(),
  label: z.string(),
  model_id: z.string().nullable(),
  model_revision: z.string().nullable(),
  detail: z.string(),
});

export type AppHealth = z.infer<typeof appHealthSchema>;
export type ModelReadiness = z.infer<typeof modelReadinessSchema>;
export type ServiceStatus = { health: AppHealth; model: ModelReadiness };
export type FetchLike = (input: string, init?: { signal?: AbortSignal }) => Promise<Response>;

const TIMEOUT_MS = 5000;

async function getJson<T>(url: string, schema: z.ZodType<T>, fetchImpl: FetchLike): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`Request failed with status ${response.status}`);
    }
    return schema.parse(await response.json());
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchServiceStatus(
  baseUrl: string,
  // Wrap the global fetch: a bare extracted reference loses its Window receiver.
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<ServiceStatus> {
  const [health, model] = await Promise.all([
    getJson(`${baseUrl}/health`, appHealthSchema, fetchImpl),
    getJson(`${baseUrl}/health/model`, modelReadinessSchema, fetchImpl),
  ]);
  return { health, model };
}
