import { test as base } from '@playwright/test';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export interface DockerLogMonitor {
  errors: string[];
  startMonitoring(): Promise<void>;
  stopMonitoring(): void;
  getErrors(): string[];
  clearErrors(): void;
}

export const test = base.extend<{ dockerLogs: DockerLogMonitor }>({
  dockerLogs: async ({}, use) => {
    const errors: string[];
    let monitoringProcess: any = null;
    let isMonitoring = false;

    const monitor: DockerLogMonitor = {
      errors: [],
      
      async startMonitoring() {
        if (isMonitoring) return;
        
        isMonitoring = true;
        monitor.errors = [];
        
        // Get container name/ID
        try {
          const { stdout } = await execAsync('docker ps --filter "name=nomarr" --format "{{.Names}}"');
          const containerName = stdout.trim().split('\n')[0];
          
          if (!containerName) {
            console.warn('⚠️ No nomarr container found for log monitoring');
            return;
          }
          
          console.log(`📋 Monitoring docker logs for container: ${containerName}`);
          
          // Start monitoring logs for ERROR, CRITICAL, Exception patterns
          const logProcess = exec(`docker logs -f ${containerName} 2>&1`);
          
          logProcess.stdout?.on('data', (data: string) => {
            const lines = data.toString().split('\n');
            for (const line of lines) {
              if (line.match(/ERROR|CRITICAL|Exception|Traceback|Failed|failed/i)) {
                // Filter out known non-critical errors
                if (!line.includes('404') && !line.includes('favicon')) {
                  monitor.errors.push(line);
                  console.error('🔴 Backend error:', line);
                }
              }
            }
          });
          
          monitoringProcess = logProcess;
        } catch (error) {
          console.warn('⚠️ Failed to start docker log monitoring:', error);
        }
      },
      
      stopMonitoring() {
        if (monitoringProcess) {
          monitoringProcess.kill();
          monitoringProcess = null;
        }
        isMonitoring = false;
      },
      
      getErrors(): string[] {
        return [...monitor.errors];
      },
      
      clearErrors() {
        monitor.errors = [];
      }
    };
    
    await monitor.startMonitoring();
    await use(monitor);
    monitor.stopMonitoring();
  }
});

export { expect } from '@playwright/test';

