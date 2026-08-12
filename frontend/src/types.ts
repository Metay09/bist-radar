export type Freshness={state:'FRESH'|'DELAYED'|'STALE'|'MARKET_CLOSED'|'UNKNOWN';age_minutes:number|null;label:string};
export type Candidate={symbol:string;radar_score:number;classification:string;price:number;rvol:number;early_momentum_score:number;timestamp:string;data_quality:number;market_regime:string;daily_trend:string;breakout_distance:number;disposition:string;};
export type Summary={provider:string;provider_health:string;paper_mode:boolean;research_only:boolean;market_open:boolean;data_timestamp:string|null;freshness:Freshness;counts:Record<string,number>;last_scan:string|null};
export type Signal=Candidate&{signal_id:string;lifecycle:string};
export type Bar={timestamp:string;open:number;high:number;low:number;close:number;volume:number};
export type Detail={symbol:string;candidate:Candidate|null;bars:Bar[];progression:Signal[];freshness:Freshness};
