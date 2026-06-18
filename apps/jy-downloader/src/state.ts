import { atom } from "jotai";

export type LogLevel = "info" | "success" | "error";
export type SourceMode = "url" | "file";

export interface LogEntry {
  id: number;
  level: LogLevel;
  message: string;
}

export interface InstallResult {
  targetDir: string;
  placeholderId: string;
  draftName: string;
}

export interface InstallStep {
  key: string;
  message: string;
  level: LogLevel;
}

export const sourceAtom = atom("");
export const sourceModeAtom = atom<SourceMode>("url");
export const draftsDirAtom = atom("");
export const draftNameAtom = atom("");
export const placeholderIdAtom = atom("");
export const overwriteAtom = atom(false);
export const installingAtom = atom(false);
export const resultAtom = atom<InstallResult | null>(null);
export const logsAtom = atom<LogEntry[]>([]);
export const currentStepAtom = atom<InstallStep | null>(null);

export const canInstallAtom = atom((get) => {
  const source = get(sourceAtom).trim();
  const sourceMode = get(sourceModeAtom);
  const hasValidSource = sourceMode === "url"
    ? source.startsWith("http://") || source.startsWith("https://")
    : source.toLowerCase().endsWith(".zip");
  return hasValidSource && get(draftsDirAtom).trim().length > 0 && !get(installingAtom);
});

let nextLogId = 1;

export const appendLogAtom = atom(null, (_get, set, entry: Omit<LogEntry, "id">) => {
  set(logsAtom, (logs) => [...logs, { ...entry, id: nextLogId++ }]);
});

export const setCurrentStepAtom = atom(null, (_get, set, step: InstallStep | null) => {
  set(currentStepAtom, step);
});

export const clearRunStateAtom = atom(null, (_get, set) => {
  set(resultAtom, null);
  set(logsAtom, []);
  set(currentStepAtom, null);
});
