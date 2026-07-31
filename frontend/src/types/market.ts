export interface IndexMark {
  label: string;
  stock_code: string;
  exchange: string;
  ltp: number | null;
  previous_close: number | null;
  change_pct: number | null;
  ts: string | null;
  stale: boolean;
  error?: string | null;
}

export interface MarketIndicesResponse {
  as_of: string | null;
  indices: IndexMark[];
}
