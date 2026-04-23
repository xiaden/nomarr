const CANONICAL_TEST_LIBRARY_PATH = '/app/tests/fixtures/library/good';

export function getLibraryPathCandidates(): string[] {
  return [process.env.E2E_TEST_LIBRARY_PATH ?? CANONICAL_TEST_LIBRARY_PATH];
}

export function resolveTestLibraryPath(): string {
  return getLibraryPathCandidates()[0];
}

export const TEST_LIBRARY_PATH = resolveTestLibraryPath();
