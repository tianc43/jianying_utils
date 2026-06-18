import { invoke } from "@tauri-apps/api/core";

export interface EnvironmentInfo {
  defaultDraftsDir: string | null;
  detectedPlaceholderId: string | null;
}

export interface InstallDraftRequest {
  source: string;
  draftsDir: string;
  draftName?: string;
  placeholderId?: string;
  overwrite: boolean;
}

export interface InstallDraftResult {
  targetDir: string;
  placeholderId: string;
  draftName: string;
}

export interface DiagnosticsInfo {
  logDir: string;
  logFile: string;
}

export interface InstallLogEvent {
  level: "info" | "success" | "error";
  step: string;
  message: string;
}

export async function getEnvironmentInfo(): Promise<EnvironmentInfo> {
  return invoke<EnvironmentInfo>("get_environment_info");
}

export async function getDiagnosticsInfo(): Promise<DiagnosticsInfo> {
  return invoke<DiagnosticsInfo>("get_diagnostics_info");
}

export async function openLogDir(): Promise<void> {
  return invoke<void>("open_log_dir");
}

export async function installDraft(request: InstallDraftRequest): Promise<InstallDraftResult> {
  return invoke<InstallDraftResult>("install_draft", { request });
}
