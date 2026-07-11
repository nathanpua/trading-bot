export interface Account {
  equity: string | number;
  cash: string | number;
  buying_power: string | number;
  portfolio_value: string | number;
  day_pl: string | number;
  day_plpc: string | number;
  long_market_value: string | number;
  status: string;
  [key: string]: unknown;
}

export interface Position {
  symbol: string;
  qty: string | number;
  avg_entry_price: string | number;
  current_price: string | number;
  market_value: string | number;
  unrealized_pl: string | number;
  unrealized_plpc: string | number;
  [key: string]: unknown;
}

export interface BotState {
  high_water?: number;
  day_start_equity?: number;
  day_start_date?: string;
  halted_until?: string | null;
  halt_reason?: string | null;
  positions?: Record<string, {
    entry: number;
    entry_date: string;
    high: number;
    stop: number;
  }>;
}

export interface Portfolio {
  account: Account;
  positions: Position[];
  market_open: boolean;
  state: BotState;
}

export interface Trade {
  id: number;
  ts: string;
  symbol: string;
  side: string;
  qty: number | null;
  entry_price: number | null;
  exit_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  pnl_dollars: number | null;
  pnl_pct: number | null;
  position_pct: number | null;
  risk_pct: number | null;
  thesis: string;
  outcome: string;
  strategy: string;
  regime: string;
  tags: string;
  status: string;
}

export interface TradeStats {
  overall: {
    trades: number;
    wins: number;
    losses: number;
    win_rate: number;
    total_pnl: number;
    avg_pnl_pct: number;
  } | null;
  by_strategy: StrategyStat[];
  by_symbol: SymbolStat[];
  recent_lessons: Lesson[];
}

export interface StrategyStat {
  strategy: string;
  trades: number;
  wins: number;
  win_rate: number;
  total_pnl: number;
}

export interface SymbolStat {
  symbol: string;
  trades: number;
  wins: number;
  win_rate: number;
  total_pnl: number;
}

export interface Lesson {
  category: string;
  lesson: string;
  evidence: string;
  confidence: string;
}

export interface Cycle {
  ts: string;
  phase: string;
  execute: boolean;
  regime: {
    regime: string;
    risk_multiplier: number;
    vix: number;
    vix_source: string;
    spy_trend: string;
    reasons: string[];
  };
  halt: boolean;
  halt_reason: string;
  exits: unknown[];
  entries: unknown[];
  equity: number;
  report: string;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  source: string;
}

export interface MemoryResult {
  memory: string;
  similarity: number;
  metadata: Record<string, unknown>;
}
