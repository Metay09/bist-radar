import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import App from './App';

const stamp='2026-08-13T10:00:00Z';
const freshness={state:'STALE',age_minutes:90,label:'Veri eski: 1,5 saat'};
const summary={provider:'Yahoo Finance via yfinance',provider_health:'RESEARCH_ONLY',paper_mode:true,research_only:true,market_open:true,data_timestamp:stamp,freshness,counts:{VERY_STRONG_CANDIDATE:1,PENDING_OUTCOMES:19},last_scan:stamp};
const candidate={symbol:'ASELS',radar_score:91,classification:'VERY_STRONG_CANDIDATE',price:200,rvol:2.5,early_momentum_score:88,timestamp:stamp,data_quality:100,market_regime:'NEUTRAL',daily_trend:'UPTREND',breakout_distance:-.2,disposition:'SIGNAL_UPGRADED'};
const plan={symbol:'ASELS',timestamp:stamp,reference_price:200,entry_zone_low:198,entry_zone_high:201,breakout_trigger:200,stop_price:194,stop_distance_percent:3,targets:[{price:209,return_percent:4.5},{price:215,return_percent:7.5},{price:218,return_percent:9}],risk_reward:2.5,status:'BREAKOUT_ONAYI',explanation:['RVOL yüksek','Veri eski; plan son bara dayanır.'],data_age_minutes:90,stale:true,research_only:true,position_sizing:{account_equity:100000,max_risk_percent:.75,allowed_risk_amount:750,suggested_position_value:20000,estimated_quantity:100,advisory_only:true}};
const detail={symbol:'ASELS',candidate,bars:[{timestamp:stamp,open:198,high:202,low:197,close:200,volume:100}],progression:[],freshness,trade_plan:plan};

beforeEach(()=>{localStorage.clear();sessionStorage.clear();vi.stubGlobal('fetch',vi.fn((url:string)=>Promise.resolve({ok:true,json:()=>Promise.resolve(url.includes('performance')?{realized_pnl:0,open_positions:0,closed_trades:0,mtm_equity:null}:url.includes('/symbols/')?detail:url.includes('trade-plans')?[plan]:url.includes('summary')?summary:url.includes('candidates')?[candidate]:url.includes('/signals/history')?[candidate]:url.includes('/ml/status')?{observations:19,fully_labeled:0}:url.includes('system/overview')?{database:'HEALTHY',worker_jobs:[]}:[])}))) });
afterEach(()=>cleanup());

describe('dashboard UX',()=>{
  it('renders mobile bottom nav and desktop sidebar landmarks',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');render(<MemoryRouter><App/></MemoryRouter>);
    expect(await screen.findByText('Öne Çıkan Adaylar')).toBeInTheDocument();
    expect(screen.getByLabelText('Mobil ana navigasyon')).toBeInTheDocument();
    expect(document.querySelector('.desktop-sidebar')).toBeInTheDocument();
    expect(document.querySelector('.mobile-signals')).toBeInTheDocument();
  });
  it('restores radar search and filter state after returning from detail',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');
    sessionStorage.setItem('bist-radar-query','ASE');
    sessionStorage.setItem('bist-radar-strength','VERY_STRONG_CANDIDATE');
    render(<MemoryRouter><App/></MemoryRouter>);
    expect(await screen.findByDisplayValue('ASE')).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Çok Güçlü'})).toHaveClass('active');
  });
  it('opens, dismisses, persists and reopens guided tour',()=>{
    render(<MemoryRouter><App/></MemoryRouter>);expect(screen.getByText('BIST Radar’a hoş geldiniz')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Atla'));expect(localStorage.getItem('bist-radar-tour-seen')).toBe('1');
    fireEvent.click(screen.getByLabelText('Rehberi aç'));expect(screen.getByText('BIST Radar’a hoş geldiniz')).toBeInTheDocument();
  });
  it('renders trade plan warning, sizing, chart and tabs',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');render(<MemoryRouter initialEntries={['/symbol/ASELS']}><App/></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:/İşlem Planı/})).toBeInTheDocument();
    expect(screen.getByText(/Güncel piyasa verisi alınamadığı için bu işlem planı/)).toBeInTheDocument();
    expect(screen.getByText('Güncel veri yok — plan uygulanabilir değil')).toBeInTheDocument();
    expect(screen.getByText(/Veri 90 dk eski/)).toBeInTheDocument();expect(screen.getByText(/Önerilen pozisyon boyutu/)).toBeInTheDocument();
    expect(screen.getByRole('tab',{name:'Sinyal Geçmişi'})).toBeInTheDocument();fireEvent.click(screen.getByRole('tab',{name:'Grafik'}));
    expect(screen.getByLabelText(/Mum grafiği/)).toBeInTheDocument();
  });
  it('renders signal mobile cards and contextual help',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');render(<MemoryRouter initialEntries={['/signals']}><App/></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'Sinyaller'})).toBeInTheDocument();expect(document.querySelector('.history-card')).toBeInTheDocument();
    expect(screen.getByText(/Sonucu bekleniyor/)).toBeInTheDocument();
  });
  it('does not render a null outcome as zero and converts return ratios to percent',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');
    vi.stubGlobal('fetch',vi.fn((url:string)=>Promise.resolve({ok:true,json:()=>Promise.resolve(url.includes('/signals/outcomes')?[{signal_id:'s1',forward_return_15m:.0125,maximum_favorable_excursion:.02}]:url.includes('/signals/history')?[{...candidate,signal_id:'s1',lifecycle:'PARTIALLY_LABELED'}]:[])})));
    render(<MemoryRouter initialEntries={['/signals']}><App/></MemoryRouter>);
    expect(await screen.findByText('%1,25')).toBeInTheDocument();
    expect(screen.getByText('%2,00')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
  it('shows shadow insufficient data warning',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');render(<MemoryRouter initialEntries={['/analysis']}><App/></MemoryRouter>);
    expect((await screen.findAllByText(/Henüz tüm takip ufukları sonuçlanmış sinyal yok/)).length).toBeGreaterThan(0);expect(screen.getByText(/synthetic production veri yoktur/)).toBeInTheDocument();
  });
  it('handles provider failure',async()=>{
    localStorage.setItem('bist-radar-tour-seen','1');vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:false,status:503})));render(<MemoryRouter><App/></MemoryRouter>);
    await waitFor(()=>expect(screen.getByText(/Veri servisine ulaşılamıyor/)).toBeInTheDocument());
  });
});
