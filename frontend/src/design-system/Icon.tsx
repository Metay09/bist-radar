import type { ReactNode } from "react";

const paths: Record<string, ReactNode> = {
  radar: <><circle cx="12" cy="12" r="8"/><path d="M12 4v8l5 3"/><circle cx="12" cy="12" r="2"/></>,
  tracking: <><path d="M4 18V8m6 10V4m6 14v-6m4 6H2"/><path d="m3 11 6-4 6 3 5-5"/></>,
  history: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2M3 12H1"/></>,
  analysis: <><path d="M4 19V9m6 10V5m6 14v-7m4 7H2"/><path d="m3 7 6-4 6 5 5-5"/></>,
  system: <><circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M19 5l-2 2M7 17l-2 2"/></>,
};

export function Icon({ name }: { name: string }) {
  return <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}
