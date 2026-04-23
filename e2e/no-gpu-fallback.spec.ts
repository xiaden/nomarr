import { authenticatedApiRequest } from './fixtures/api-helpers';
import { expect, test } from './fixtures/auth';

type JsonRecord = Record<string, unknown>;

function assertJsonObject(value: unknown, label: string): asserts value is JsonRecord {
  expect(value, `${label} should not be null`).not.toBeNull();
  expect(Array.isArray(value), `${label} should be a JSON object, not an array`).toBe(false);
  expect(typeof value, `${label} should be a JSON object`).toBe('object');
}

function assertNoGpuFallbackContract(body: JsonRecord): void {
  expect(typeof body['available']).toBe('boolean');
  expect(typeof body['monitor_healthy']).toBe('boolean');

  const errorSummary = body['error_summary'];
  expect(errorSummary === null || typeof errorSummary === 'string').toBe(true);

  expect('detail' in body, 'GPU health endpoint should return its contract, not an API error wrapper').toBe(false);
  expect('error' in body, 'GPU health endpoint should not report a fatal top-level error').toBe(false);
  expect('errors' in body, 'GPU health endpoint should not report fatal validation errors').toBe(false);
}

test.describe('No-GPU fallback coverage', () => {
  test('should report non-fatal GPU health in degraded or CPU-only mode', async ({ authenticatedPage: page }) => {
    const response = await authenticatedApiRequest(page, '/api/web/health/gpu');

    expect(response.status(), 'GET /api/web/health/gpu should return HTTP 200').toBe(200);

    const responseText = await response.text();
    expect(responseText.trim().length, 'GET /api/web/health/gpu should return a JSON body').toBeGreaterThan(0);

    let responseBody: unknown = null;
    expect(() => {
      responseBody = JSON.parse(responseText) as unknown;
    }, 'GET /api/web/health/gpu should return valid JSON').not.toThrow();

    assertJsonObject(responseBody, 'GET /api/web/health/gpu response');
    assertNoGpuFallbackContract(responseBody);
  });
});
