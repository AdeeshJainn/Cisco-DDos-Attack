// Manual choice (persisted) wins over system preference; dark is the
// default for the mission-control surface. index.html applies the stored
// theme before first paint so there is no flash.
import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "theme";
const listeners = new Set<() => void>();

export function getTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(STORAGE_KEY, theme);
  for (const notify of listeners) notify();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme);
}
