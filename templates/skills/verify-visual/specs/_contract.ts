import * as fs from 'node:fs';
import * as path from 'node:path';

export interface Viewport {
  width: number;
  height: number;
  device?: string;
}

export interface Route {
  id: string;
  url: string;
  wait_for: string;
  viewports?: string[];
}

export interface Component {
  id: string;
  selector: string;
  route?: string;
  trigger?: string;
  viewports?: string[];
}

export interface InteractionStep {
  focus?: string;
  click?: string;
  type?: string;
  key?: string;
  wait?: number;
  expect?: string;
}

export interface Interaction {
  id: string;
  route?: string;
  viewport?: string;
  steps: InteractionStep[];
}

export interface PerformanceBudgets {
  lcp_ms?: number;
  cls?: number;
}

export interface VisionCheck {
  provider: 'none' | 'gemini' | 'manual';
  blocking?: boolean;
  budget_per_run?: number;
  prompts?: string[];
}

export interface Contract {
  name: string;
  base_url?: string;
  viewports: Record<string, Viewport>;
  routes?: Route[];
  components?: Component[];
  interactions?: Interaction[];
  pixel_diff_threshold?: number;
  performance_budgets?: PerformanceBudgets;
  vision_check?: VisionCheck;
}

export function loadContract(): Contract {
  const explicit = process.env.VISUAL_CONTRACT;
  const candidates = [
    explicit,
    path.resolve(__dirname, '..', 'visual-contract.json'),
  ].filter(Boolean) as string[];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      const raw = fs.readFileSync(p, 'utf-8');
      return JSON.parse(raw) as Contract;
    }
  }
  throw new Error(
    `visual-contract.json not found. Tried: ${candidates.join(', ')}. ` +
    `Copy visual-contract.example.json to visual-contract.json and edit for your project.`
  );
}

export function viewportSize(contract: Contract, id: string): { width: number; height: number } {
  const v = contract.viewports?.[id];
  if (!v) throw new Error(`unknown viewport: ${id}`);
  return { width: v.width, height: v.height };
}

export function routeUrl(contract: Contract, url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  const base = (contract.base_url ?? 'http://localhost:3000').replace(/\/$/, '');
  return base + (url.startsWith('/') ? url : '/' + url);
}

export function routeById(contract: Contract, id?: string): Route | undefined {
  if (!id) return contract.routes?.[0];
  return contract.routes?.find(r => r.id === id);
}

export function routesFor(route: Route): string[] {
  return route.viewports?.length ? route.viewports : ['desktop'];
}

export function componentViewports(contract: Contract, comp: Component): string[] {
  if (comp.viewports?.length) return comp.viewports;
  return Object.keys(contract.viewports ?? {}).slice(0, 1);
}
