export interface BackendLaunchConfig {
  projectRoot: string;
  workingDirectory: string;
  command: string;
  args: string[];
  host: string;
  port: number;
  nexusHome: string;
  frontendDist: string;
}

export interface BackendRuntime {
  url: string;
  pid: number | null;
  stop: () => Promise<void>;
}
