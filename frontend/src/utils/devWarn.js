export function devWarn(...args) {
  if (import.meta.env?.DEV) console.warn(...args);
}
