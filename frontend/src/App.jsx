import React, { useEffect, useRef, useState } from 'react';
import { Activity, ArrowDown, ArrowDownRight, ArrowRight, ArrowUpRight, ChartNoAxesCombined, Check, ChevronDown, Clock3, Compass, Database, Download, Globe2, History, Info, Layers3, LoaderCircle, Plane, Plus, Search, ShieldCheck, Sparkles, X } from 'lucide-react';
import WorldMap from './WorldMap';
import AirportPicker from './AirportPicker';
import Observations from './Observations';
import { request, euro, labels } from './api';

const initialDate = new Date(); initialDate.setDate(initialDate.getDate() + 30);
const initial = { origin: 'VNO', destination: 'LHR', departure_date: initialDate.toISOString().slice(0,10), return_date: '', markets: ['LT','GB','US'], baseline_market: 'LT', adults: 1, cabin: 'ECONOMY', checked_baggage: {pieces: 1, weight_kg: 23}, data_mode: 'MOCK' };
const marketCode = { LT: 'LT', GB: 'UK', US: 'US', DE: 'DE' };

function PanelTitle({ eyebrow, title, children }) { return <div className="panel-title"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{children}</div>; }
function StatusDot({ available }) { return <span className={`status-dot ${available ? 'online' : ''}`}/>; }

export default function App() {
  const [view, setView] = useState('dashboard');
  const [criteria, setCriteria] = useState(initial);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [health, setHealth] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [active, setActive] = useState('GB');
  const [mapAirports,setMapAirports]=useState([]);
  const [details, setDetails] = useState(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [aiReply, setAiReply] = useState(null);
  const dialogRef = useRef(null);
  const modeChosen = useRef(false);

  const loadHistory = async (next = null) => {
    const data = await request(`/searches?limit=10${next ? `&cursor=${next}` : ''}`);
    setHistory(old => next ? [...old, ...data.items] : data.items); setCursor(data.next_cursor);
  };
  useEffect(() => {
    request('/health/ready').then(setHealth).catch(() => setHealth({status:'offline', agent:false}));
    request('/capabilities').then(data=>{setCapabilities(data);if(!modeChosen.current && data.real.configured)setCriteria(old=>({...old,data_mode:'REAL'}));}).catch(()=>{});
    loadHistory().catch(() => {});
  }, []);
  useEffect(() => {
    if (details) dialogRef.current?.showModal(); else dialogRef.current?.close();
  }, [details]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(timer); }, [notice]);

  const applyResult = data => { modeChosen.current=true; setResult(data); setCriteria({...data.criteria, return_date:data.criteria.return_date || ''}); setView('dashboard'); setActive(data.offers.find(o => data.comparison_groups.some(g => g.offers[0]?.offer_id === o.id))?.market || 'GB'); };
  async function search(event) {
    event?.preventDefault(); setError(''); setBusy(true); setAiReply(null);
    try {
      const data = await request('/searches', {method:'POST', body:JSON.stringify({...criteria, return_date:criteria.return_date || null})});
      applyResult(data); await loadHistory();
    } catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  async function askAgent(event) {
    event.preventDefault(); if (!prompt.trim()) return;
    setBusy(true); setError('');
    try {
      const reply = await request('/agent/messages', {method:'POST',body:JSON.stringify({message:prompt,locale:'lt-LT',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,criteria_context:{...(aiReply?.interpreted_criteria || {}),...criteria,return_date:criteria.return_date || null}})});
      setAiReply(reply);
      if (reply.interpreted_criteria) setCriteria(old=>({...old,...reply.interpreted_criteria,return_date:reply.interpreted_criteria.return_date || '',data_mode:old.data_mode}));
      if (reply.search_id) { applyResult(await request(`/searches/${reply.search_id}`)); await loadHistory(); }
    } catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  const ranked = result?.comparison_groups.flatMap(group => group.offers.map(row => ({...row, group, offer:result.offers.find(o => o.id === row.offer_id)}))).sort((a,b) => Number(a.total_eur)-Number(b.total_eur)) || [];
  const best = ranked[0];
  const isReal = (result?.data_mode || criteria.data_mode) === 'REAL';
  const observations = result?.observations || [];
  const observedBest = observations.reduce((best,item)=>!best || Number(item.price.amount)<Number(best.price.amount)?item:best,null);
  const activeRow = ranked.find(row => row.offer.market === active);
  const excluded = result?.excluded_offers || [];
  const selectedMarkets = result?.criteria.markets || criteria.markets;
  const baseline = best?.group.offers.find(row => row.offer_id === best.group.baseline_offer_id);
  const discount = Math.max(0, Number(best?.savings_percent || 0));
  const change = (field, value) => {setResult(null);setAiReply(null);setCriteria(old => ({...old,[field]:value}));};
  const mapFlight = isReal?(observations.find(o=>o.localization_country===active) || observedBest):null;
  const mapSegments = mapFlight?.segments || best?.offer.segments || [];
  const routeCodes = mapSegments.length?[mapSegments[0].origin,...mapSegments.map(s=>s.destination)]:[criteria.origin,criteria.destination];
  const routeKey=routeCodes.join('|');
  useEffect(()=>{
    let cancelled=false;
    setMapAirports([]);
    Promise.all(routeKey.split('|').map(code=>request(`/airports/${encodeURIComponent(code)}`)))
      .then(airports=>{if(!cancelled)setMapAirports(airports);}).catch(()=>{if(!cancelled)setMapAirports([]);});
    return ()=>{cancelled=true;};
  },[routeKey]);
  const showOffer = offer => setDetails(offer);
  function download() {
    const blob = new Blob([JSON.stringify(result,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob); const a=document.createElement('a');a.href=url;a.download=`cheaper-air-${result.search_id}.json`;a.click();URL.revokeObjectURL(url);setNotice('Search snapshot exported.');
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => {e.preventDefault();setView('dashboard');}} aria-label="Cheaper Air dashboard"><div className="brand-icon"><Plane size={23}/></div><span>cheaper<span className="brand-light">air</span><small>FLIGHT INTELLIGENCE</small></span></a>
      <div className="workspace"><span className="workspace-icon">CA</span><div>Personal workspace<small>Local development</small></div><ChevronDown size={13}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Main navigation">
        <button className={view==='dashboard'?'nav-item selected':'nav-item'} onClick={()=>setView('dashboard')}><Layers3 size={17}/>Overview<span className="nav-indicator"/></button>
        <button className={view==='history'?'nav-item selected':'nav-item'} onClick={()=>{setView('history');loadHistory().catch(e=>setError(e.message));}}><History size={17}/>Search history<span className="count">{history.length}{cursor?'+':''}</span></button>
        <button className={view==='method'?'nav-item selected':'nav-item'} onClick={()=>setView('method')}><ShieldCheck size={17}/>How it works</button>
      </nav>
      <div className="sidebar-note"><div className="note-icon"><Globe2 size={21}/></div><strong>A wider view.<br/>A better fare.</strong><p>Compare the same flight across sales markets.</p><span className="tiny-tag">LOCAL AI EXPERIMENT</span></div>
      <div className="sidebar-bottom"><span className="avatar">A</span><div>Local explorer<small>Portfolio edition</small></div><span className="version">v0.1</span></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>{view==='history'?'Search history':view==='method'?'Methodology':'Overview'}</strong></div><div className="topbar-right"><span className="connection"><StatusDot available={health?.structured_search}/> {health?.structured_search?'API connected':health?.status==='offline'?'API offline':'Connecting'}</span><span className="topbar-divider"/><span className={isReal?"real-badge":"mock-badge"}><span/>{isReal?"REAL API":"MOCK DATA"}</span><span className="avatar small">A</span></div></header>
      <main>
        <div className="page-heading"><div className="heading-copy"><div className="eyebrow"><span className="gold-line"/> YOUR NEXT FLIGHT, A DIFFERENT PERSPECTIVE</div><h1>{view==='history'?'Your search history':view==='method'?'Built on verifiable facts.':'Flight intelligence'}</h1><p>{view==='history'?'Every search, saved with its original prices and conditions.':view==='method'?'Local AI interprets. Deterministic code compares.':'One flight. Different markets. Discover the difference.'}</p></div><div className="heading-action"><span className="date-label">LOCAL AI / V1</span><button className="button secondary" onClick={()=>{setView('dashboard');setAiOpen(x=>!x);}}><Sparkles size={15}/> AI flight search</button></div></div>
        {error && <div className="alert error" role="alert"><Info size={17}/><span>{error}</span><button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}
        {notice && <div className="toast" role="status"><Check size={16}/>{notice}</div>}
        {view === 'dashboard' && <>
          <section className="search-panel panel">
            <div className="search-top"><span><Search size={14}/> EXPLORE A ROUTE</span><div className="mode-controls"><label>DATA SOURCE <select aria-label="Data source" value={criteria.data_mode} onChange={e=>{modeChosen.current=true;change('data_mode',e.target.value);setResult(null);setAiReply(null);setError('');}}><option value="MOCK">MOCK demo</option><option value="REAL">REAL · SerpApi</option></select></label></div></div>
            <form className="search-form" onSubmit={search}>
              <AirportPicker label="Origin" value={criteria.origin} onChange={value=>change('origin',value)}/>
              <div className="route-arrow"><ArrowRight size={16}/></div>
              <AirportPicker label="Destination" value={criteria.destination} onChange={value=>change('destination',value)}/>
              <label className="date-field"><span>DEPARTURE</span><input aria-label="Departure date" type="date" required min={new Date().toISOString().slice(0,10)} value={criteria.departure_date} onChange={e=>change('departure_date',e.target.value)}/></label>
              <label className="date-field return-field"><span>RETURN <small>OPTIONAL</small></span><input aria-label="Return date" type="date" min={criteria.departure_date} value={criteria.return_date} onChange={e=>change('return_date',e.target.value)}/></label>
              <button className="button primary search-button" disabled={busy} type="submit">{busy?<LoaderCircle className="spin" size={17}/>:<Search size={17}/>} {busy?'Searching…':criteria.data_mode==='REAL'?'Search real flights':'Compare MOCK fares'}<ArrowUpRight size={16}/></button>
            </form>
            <div className="search-bottom"><div className="market-controls"><span>SALES MARKETS</span>{['LT','GB','US','DE'].map(m=><button type="button" key={m} aria-pressed={criteria.markets.includes(m)} className={`market-chip ${criteria.markets.includes(m)?'on':''}`} onClick={()=>{const next=criteria.markets.includes(m)?criteria.markets.filter(x=>x!==m):[...criteria.markets,m];if(!next.length)return;if(criteria.data_mode==='REAL'&&next.length>3){setNotice('REAL search supports up to 3 localization countries per request.');return;}setCriteria(old=>({...old,markets:next,baseline_market:next.includes(old.baseline_market)?old.baseline_market:next[0]}));}}>{criteria.markets.includes(m)?<Check size={10}/>:<Plus size={10}/>} {marketCode[m]}</button>)}</div><div className="search-options"><label>Baseline <select aria-label="Baseline market" value={criteria.baseline_market} onChange={e=>change('baseline_market',e.target.value)}>{criteria.markets.map(m=><option key={m} value={m}>{marketCode[m]}</option>)}</select></label><label><select aria-label="Checked baggage" value={criteria.checked_baggage.pieces} onChange={e=>change('checked_baggage',{pieces:Number(e.target.value),weight_kg:Number(e.target.value)?23:0})}><option value="1">23 kg checked bag</option><option value="0">No checked bag required</option></select></label></div></div>
          </section>
          {criteria.data_mode==='MOCK' && <div className="real-mode-note"><Info size={14}/>MOCK demonstration only: VNO → LHR / MIA. To search Kaunas, Warsaw, Tokyo or another route, choose REAL · SerpApi above.</div>}
          {criteria.data_mode==='REAL' && <div className="real-mode-note"><Info size={14}/>{capabilities?.real.configured?'SerpApi configured. Up to 3 localization countries per search. Actual route availability depends on the provider.':'REAL adapter ready. Add SERPAPI_API_KEY to the local .env and restart the backend. Global airport lookup works without a key.'}</div>}
          {aiOpen && <section className="ai-panel panel"><PanelTitle eyebrow="POWERED BY LOCAL OLLAMA" title="Kur norėtum skristi?"><button className="icon-button" aria-label="Close AI search" onClick={()=>setAiOpen(false)}><X size={18}/></button></PanelTitle><form onSubmit={askAgent}><textarea aria-label="Natural language flight request" placeholder="Pvz.: noriu į Majamį. Naudosiu aukščiau pasirinktas datas, išvykimo vietą ir rinkas." value={prompt} onChange={e=>setPrompt(e.target.value)} required/><button className="button primary" disabled={busy}>{busy?<LoaderCircle className="spin" size={16}/>:<Sparkles size={16}/>} Ask local AI</button></form>{aiReply && <p className="agent-reply" role="status">{aiReply.clarification?.question || aiReply.explanation?.summary}</p>}<small>Naudojami formos pasirinkimai: {criteria.origin} → {criteria.destination}, {criteria.departure_date}. Režimas: {criteria.data_mode}. Oro uostų katalogas globalus; REAL naudoja SerpApi raktą, MOCK pateikia demonstracijas. AI gali užtrukti iki 180 s.</small></section>}
          <div className="metrics-grid">
            <article className="metric panel"><div className="metric-label">{isReal?'LOWEST OBSERVED PRICE':'LOWEST COMPARABLE FARE'} <span className="metric-icon gold"><ArrowDownRight size={17}/></span></div><div className="metric-value">{isReal?(observedBest?euro(observedBest.price.amount):'—'):(best?euro(best.total_eur):'—')}<span>EUR</span></div><div className="metric-footer">{isReal?<span className="subtle">{observedBest?'Unverified fare conditions':'API observations only'}</span>:best?<><span className="gold-dot"/>{labels[best.offer.market]} market <span className="subtle">/ {best.offer.total.currency}</span></>:<span className="subtle">Run a search to discover fares</span>}</div></article>
            <article className="metric panel"><div className="metric-label">BASELINE MARKET FARE <span className="metric-icon"><Globe2 size={17}/></span></div><div className="metric-value">{baseline?euro(baseline.total_eur):'—'}<span>EUR</span></div><div className="metric-footer"><span className="blue-dot"/>{labels[result?.criteria.baseline_market || criteria.baseline_market]}<span className="subtle"> / reference market</span></div></article>
            <article className="metric panel savings-metric"><div className="metric-label">POTENTIAL SAVINGS <span className="metric-icon gold"><ChartNoAxesCombined size={17}/></span></div><div className="metric-value gold-text">{best?.savings_eur != null?euro(best.savings_eur):'—'}{best?.savings_percent != null && <span className="saving-pill"><ArrowDown size={11}/>{best.savings_percent}%</span>}</div><div className="metric-footer"><ShieldCheck size={13}/><span className="subtle">{isReal?'Not verified · savings unavailable':'Matched flight & fare conditions'}</span></div></article>
            <article className="metric panel"><div className="metric-label">{isReal?'SEARCH COUNTRIES':'MARKETS COMPARED'} <span className="metric-icon"><Compass size={17}/></span></div><div className="metric-value">{result?new Set(isReal?observations.map(o=>o.localization_country):ranked.map(r=>r.offer.market)).size.toString().padStart(2,'0'):'—'}<span className="market-fraction">/ {selectedMarkets.length.toString().padStart(2,'0')}</span></div><div className="metric-footer"><span className="blue-dot"/><span className="subtle">{isReal?'Localization ≠ verified point of sale':result?`${excluded.length} offer${excluded.length===1?'':'s'} excluded`:'Same flight. Equal conditions.'}</span></div></article>
          </div>
          <div className="visual-grid">
            <section className="map-panel panel"><PanelTitle eyebrow="A GLOBAL PERSPECTIVE" title="Your flight route"><span className="live-tag"><span/>{isReal?'SELECTED FLIGHTS':'MOCK ROUTE'}</span></PanelTitle><WorldMap airports={mapAirports}/><div className="map-footer"><div className="map-route"><span className="blue-dot"/>{result?.criteria.origin || criteria.origin}<span className="route-line"/><Plane size={15}/><span className="route-line"/>{result?.criteria.destination || criteria.destination}</div><div className="map-offer">{isReal?<div className="route-market-controls">{selectedMarkets.map(m=><button key={m} className={active===m?'selected':''} onClick={()=>setActive(m)} aria-label={`Show ${labels[m] || m} flight route`}>{marketCode[m] || m}</button>)}</div>:activeRow?<><span>{labels[active]} sales market</span><strong>{euro(activeRow.total_eur)}</strong><button aria-label={`View ${labels[active]} offer`} className="icon-button" onClick={()=>showOffer(activeRow.offer)}><ArrowUpRight size={16}/></button></>:<span className="subtle">{result?'No comparable offer in this market':'Select a market · run a search to compare'}</span>}</div></div></section>
            <section className="insight-panel panel"><PanelTitle eyebrow="THE PRICE DIFFERENCE" title="A closer look"><Activity size={17} className="subtle"/></PanelTitle><div className="donut-wrap"><svg viewBox="0 0 180 180" aria-label={best?`${discount}% savings versus baseline`:'No price comparison yet'}><circle cx="90" cy="90" r="70" fill="none" stroke="#1b2d44" strokeWidth="13"/><circle cx="90" cy="90" r="70" fill="none" stroke="#669dcb" strokeWidth="13" strokeDasharray={`${Math.max(0,100-discount)*4.398} 439.8`} transform="rotate(-90 90 90)"/><circle cx="90" cy="90" r="70" fill="none" stroke="#eab459" strokeWidth="13" strokeDasharray={`${discount*4.398} 439.8`} strokeDashoffset={-(100-discount)*4.398} transform="rotate(-90 90 90)"/></svg><div className="donut-center"><strong>{best?.savings_percent!=null?`${best.savings_percent}%`:'—'}</strong><span>potential savings</span></div></div><div className="legend"><span><i className="blue-dot"/>Comparable fare</span><span><i className="gold-dot"/>Savings</span></div><div className="insight-note"><ShieldCheck size={17}/><p>{best?'Same itinerary. Same baggage. Same fare rules.':'Compare like for like. Only equivalent offers enter the same group.'}<small>Purchase eligibility is not verified.</small></p></div></section>
          </div>
          {isReal && observations.length>0 && <Observations key={result.search_id} items={observations} searchId={result.search_id}/>}
          <section className="results-panel panel"><PanelTitle eyebrow="COMPARE WITH CONFIDENCE" title="Market breakdown"><button className="button text-button" disabled={!result} onClick={download}><Download size={14}/>Export results</button></PanelTitle>{ranked.length?<div className="table-scroll"><table><thead><tr><th>SALES MARKET</th><th>ORIGINAL FARE</th><th>TOTAL IN EUR</th><th>VS. BASELINE</th><th>PRICE COMPARISON</th><th/></tr></thead><tbody>{ranked.map((row,i)=><tr key={row.offer_id} className={active===row.offer.market?'active-row':''} onClick={()=>setActive(row.offer.market)}><td><div className="market-name"><span className="country-token">{marketCode[row.offer.market]}</span><span><strong>{labels[row.offer.market]}</strong><small>{row.offer.conditions.fare_product.replace('MOCK-','')} · Group {row.group.id.slice(0,4)}</small></span>{row.group.offers[0].offer_id===row.offer_id && <span className="best-tag">BEST IN GROUP</span>}</div></td><td className="mono">{new Intl.NumberFormat('en-IE',{style:'currency',currency:row.offer.total.currency}).format(Number(row.offer.total.amount))}</td><td className="price-cell mono">{euro(row.total_eur)}</td><td className={Number(row.savings_eur)>0?'gold-text mono':'subtle mono'}>{row.savings_eur == null?'No baseline':row.offer_id===row.group.baseline_offer_id?<span className="baseline-tag">BASELINE</span>:`${Number(row.savings_eur)>0?'−':'+'}${euro(Math.abs(Number(row.savings_eur)))}`}</td><td><div className="price-bar"><span style={{width:`${Number(row.total_eur)/Math.max(...ranked.map(r=>Number(r.total_eur)))*100}%`}} className={row.group.offers[0].offer_id===row.offer_id?'gold-bar':''}/></div></td><td><button className="icon-button" aria-label={`View ${labels[row.offer.market]} ${row.offer.conditions.fare_product} details`} onClick={e=>{e.stopPropagation();showOffer(row.offer);}}><ArrowUpRight size={17}/></button></td></tr>)}</tbody></table></div>:<div className="empty-state"><Globe2 size={30}/><strong>{isReal&&observations.length?'Verified fare comparison unavailable':result?'No flight price data for this route':'A better perspective starts with a search.'}</strong><p>{isReal?(observations.length?'Observed prices appear above. Missing fare conditions prevent an equivalent-fare savings calculation.':result?'The provider returned no flights for these dates and airports. Try different dates or a nearby departure airport, such as Vilnius instead of Kaunas.':'Select any worldwide airports and search with your configured SerpApi key.'):result?'No MOCK scenario for this route. Select REAL to request API prices for worldwide IATA airports.':'Choose your route and compare the same flight across sales markets.'}</p></div>}
            {excluded.length>0 && <details className="excluded"><summary><ShieldCheck size={14}/>{excluded.length} offer{excluded.length===1?'':'s'} excluded from comparison<ChevronDown size={14}/></summary>{excluded.map(item=><div key={item.offer_id} className="excluded-item"><span>{item.offer_id}</span><span>{item.reason_codes.map(r=>r.toLowerCase().replaceAll('_',' ')).join(' · ')}</span><button className="button text-button" onClick={()=>showOffer(result.offers.find(o=>o.id===item.offer_id))}>Details <ArrowUpRight size={12}/></button></div>)}</details>}
          </section>
          {result && <div className="result-provenance"><Clock3 size={12}/>Snapshot {new Date(result.created_at).toLocaleString()}<span>·</span>{result.fx_snapshot_id?`FX: ${result.fx_snapshot_id}`:'Provider prices requested in EUR · no MOCK FX'}<span>·</span>{result.status}<span>·</span>{isReal?'Observed snapshot — recheck at source':result.offers.every(o=>new Date(o.expires_at)>new Date())?'Check offer expiry in details':'Historical snapshot — offers expired'}</div>}
          {result?.warnings.filter(w=>!w.startsWith('MOCK:')&&!w.startsWith('Purchase')).map(w=><p className="result-warning" key={w}><Info size={13}/>{w}</p>)}
        </>}
        {view==='history' && <section className="panel history-panel"><PanelTitle title="Saved searches"><button className="button secondary" onClick={()=>loadHistory().catch(e=>setError(e.message))}><History size={14}/>Refresh</button></PanelTitle>{!history.length?<div className="empty-state"><History size={30}/><strong>No saved searches yet</strong><p>Your comparisons will appear here after your first search.</p><button className="button primary" onClick={()=>setView('dashboard')}>Explore a route <ArrowRight size={15}/></button></div>:history.map(item=><button className="history-row" key={item.search_id} onClick={()=>{applyResult(item);setNotice('Original search snapshot loaded. Prices have not been refreshed.');}}><span className="history-plane"><Plane size={20}/></span><span><strong>{item.criteria.origin} <ArrowRight size={13}/> {item.criteria.destination}</strong><small>{item.criteria.departure_date}{item.criteria.return_date?` → ${item.criteria.return_date}`:' · One way'}</small></span><span className="history-meta">{item.criteria.markets.map(m=>marketCode[m]||m).join(' / ')}<small>{new Date(item.created_at).toLocaleString()}</small></span><span className={item.data_mode==='REAL'?"real-badge":"mock-badge"}>{item.data_mode}</span><ArrowUpRight size={16}/></button>)}{cursor&&<button className="button secondary load-more" onClick={()=>loadHistory(cursor).catch(e=>setError(e.message))}>Load more searches</button>}</section>}
        {view==='method' && <section className="method-grid">{[
          [Sparkles,'01 / INTERPRET','AI understands your request','Ollama interprets your flight request using validated tools. Missing details trigger a clarification. You can always use the structured search without AI.'],
          [ShieldCheck,'02 / MATCH','Compare equivalent offers','Segment times, carriers, fare products, baggage and ticket conditions must match. Unknown mandatory fees or conditions exclude an offer. Different fare groups have separate winners.'],
          [ChartNoAxesCombined,'03 / CALCULATE','Every number comes from code','Python Decimal converts the full price to EUR using one synthetic FX snapshot. Savings use the cheapest equivalent offer in your selected baseline market.'],
          [Database,'04 / TRACE','Demonstration, clearly labelled','MOCK is synthetic. REAL displays connected SerpApi price observations with source timestamps. Incomplete fare terms prevent confirmed savings. No booking, live availability or purchase eligibility is promised. History preserves the original result, not a refreshed quote.'],
        ].map(([Icon,eyebrow,title,text])=><article className="panel method-card" key={title}><Icon size={25}/><div className="eyebrow">{eyebrow}</div><h2>{title}</h2><p>{text}</p></article>)}</section>}
        <footer className="page-footer"><span><span className="gold-dot"/>{isReal?'REAL SOURCE OBSERVATIONS':'MOCK ENVIRONMENT'} <span className="footer-separator">/</span> {isReal?'SerpApi results. Fare conditions & purchase eligibility unverified.':'Synthetic flights, prices & exchange rates. No booking.'}</span><span>Built for exploration. Powered locally.<Plane size={12}/></span></footer>
      </main>
    </div>
    <dialog ref={dialogRef} className="offer-dialog" onCancel={()=>setDetails(null)} onClick={e=>{if(e.target===dialogRef.current)setDetails(null);}} onClose={()=>setDetails(null)}>{details && <><PanelTitle eyebrow="MOCK OFFER · NOT BOOKABLE" title="Flight & fare details"><button className="icon-button" aria-label="Close offer details" onClick={()=>setDetails(null)}><X size={20}/></button></PanelTitle><div className="detail-price"><span>{labels[details.market]} sales market</span><strong>{new Intl.NumberFormat('en-IE',{style:'currency',currency:details.total.currency}).format(Number(details.total.amount))}</strong></div>{details.segments.map((segment,i)=><div className="segment" key={i}><div className="eyebrow">{i?'RETURN':'OUTBOUND'} · {segment.marketing_carrier} {segment.flight_number}</div><div><strong>{segment.origin}</strong><Plane size={19}/><strong>{segment.destination}</strong></div><p>{new Date(segment.departure_at).toLocaleString()} → {new Date(segment.arrival_at).toLocaleString()}</p></div>)}<dl className="fare-details"><dt>Fare product</dt><dd>{details.conditions.fare_product || 'Unknown'}</dd><dt>Checked baggage</dt><dd>{details.conditions.checked_baggage?`${details.conditions.checked_baggage.pieces} × ${details.conditions.checked_baggage.weight_kg} kg`:'Unknown'}</dd><dt>Cabin baggage</dt><dd>{details.conditions.cabin_baggage?`${details.conditions.cabin_baggage.pieces} × ${details.conditions.cabin_baggage.weight_kg} kg`:'Unknown'}</dd><dt>Refundable</dt><dd>{details.conditions.refundable===null?'Unknown':details.conditions.refundable?'Yes':'No'}</dd><dt>Changeable</dt><dd>{details.conditions.changeable===null?'Unknown':details.conditions.changeable?'Yes':'No'}</dd><dt>Mandatory fees included</dt><dd>{details.mandatory_fees_included?'Yes':'Unconfirmed'}</dd><dt>Expires</dt><dd>{new Date(details.expires_at).toLocaleString()}</dd><dt>Purchase eligibility</dt><dd>Not verified</dd></dl><div className="detail-notice"><Info size={16}/>Synthetic demonstration data. This offer cannot be booked.</div></>}</dialog>
  </div>;
}
