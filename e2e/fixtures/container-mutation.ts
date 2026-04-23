import { execSync } from 'child_process';

const DOCKER_EXEC_TIMEOUT_MS = 10000;

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

function getContainerName(): string {
  // Container name matches container_name in docker/compose.yaml; override via NOMARR_CONTAINER_NAME.
  return process.env.NOMARR_CONTAINER_NAME ?? 'nomarr';
}

export function createContainerFile(filePath: string, content: string = ''): void {
  const containerName = getContainerName();
  const writeCommand = `printf %s ${shellQuote(content)} > ${shellQuote(filePath)}`;

  execSync(`docker exec ${shellQuote(containerName)} sh -c ${shellQuote(writeCommand)}`, {
    stdio: 'pipe',
    timeout: DOCKER_EXEC_TIMEOUT_MS,
  });
}

export function deleteContainerFile(filePath: string): void {
  const containerName = getContainerName();

  execSync(`docker exec ${shellQuote(containerName)} rm -f ${shellQuote(filePath)}`, {
    stdio: 'pipe',
    timeout: DOCKER_EXEC_TIMEOUT_MS,
  });
}

export function renameContainerFile(fromPath: string, toPath: string): void {
  const containerName = getContainerName();

  execSync(`docker exec ${shellQuote(containerName)} mv ${shellQuote(fromPath)} ${shellQuote(toPath)}`, {
    stdio: 'pipe',
    timeout: DOCKER_EXEC_TIMEOUT_MS,
  });
}
