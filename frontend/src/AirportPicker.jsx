import { useEffect, useRef, useState } from 'react';
import { MapPin, LoaderCircle, X } from 'lucide-react';
import { request } from './api';

export default function AirportPicker({ label, value, onChange }) {
  const [text, setText] = useState(value);
  const [airport, setAirport] = useState(null);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [highlight, setHighlight] = useState(0);
  const root = useRef(null);
  const input = useRef(null);
  const listId = `${label.toLowerCase()}-airports`;
  useEffect(() => {
    setText(value);
    let cancelled = false;
    request(`/airports/${encodeURIComponent(value)}`).then(item => {if(!cancelled)setAirport(item);}).catch(()=>{if(!cancelled)setAirport(null);});
    return ()=>{cancelled=true;};
  }, [value]);
  useEffect(() => {
    input.current?.setCustomValidity(text === value ? '' : 'Select an airport from the suggestions.');
  }, [text, value]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(()=>{
      request(`/airports?q=${encodeURIComponent(text)}&limit=8`).then(data=>{
        if(!cancelled){setItems(data.items);setHighlight(0);setError('');}
      }).catch(e=>{if(!cancelled){setItems([]);setError(e.message);}}).finally(()=>{if(!cancelled)setLoading(false);});
    },180);
    return ()=>{cancelled=true;clearTimeout(timer);};
  },[text,open]);
  useEffect(()=>{
    const outside=e=>{if(!root.current?.contains(e.target))setOpen(false);};
    document.addEventListener('pointerdown',outside);
    return ()=>document.removeEventListener('pointerdown',outside);
  },[]);
  function select(item){if(item.type==='closed')return;setAirport(item);setText(item.code);onChange(item.code);setOpen(false);input.current?.setCustomValidity('');}
  function keydown(e){
    if(e.key==='Escape'){setOpen(false);return;}
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();setOpen(true);setHighlight(old=>Math.max(0,Math.min(items.length-1,old+(e.key==='ArrowDown'?1:-1))));}
    if(e.key==='Enter'&&open){e.preventDefault();if(items[highlight])select(items[highlight]);}
  }
  return <div className="airport-picker" ref={root}>
    <label htmlFor={`${listId}-input`}>{label==='Origin'?'FROM':'TO'}</label>
    <div className="airport-input-wrap"><MapPin size={16}/><input id={`${listId}-input`} ref={input} role="combobox" aria-label={`${label} airport`} aria-expanded={open} aria-controls={listId} aria-autocomplete="list" aria-activedescendant={open&&items[highlight]?`${listId}-${highlight}`:undefined} required autoComplete="off" value={text} placeholder="City, airport or code" onFocus={e=>{setOpen(true);e.target.select();}} onChange={e=>{setText(e.target.value);setOpen(true);}} onKeyDown={keydown}/>{loading&&open?<LoaderCircle size={13} className="spin"/>:<button type="button" className="airport-clear" aria-label={`Clear ${label.toLowerCase()} airport`} onClick={()=>{setText('');setOpen(true);input.current?.focus();}}><X size={12}/></button>}</div>
    <div className="airport-selected-name" title={airport?.name}>{text===value&&airport?`${airport.municipality || airport.name} · ${airport.country}`:'Search worldwide · city, IATA or ICAO'}</div>
    {open&&<div className="airport-dropdown"><div className="airport-dropdown-heading">GLOBAL AIRPORT DIRECTORY <span>OurAirports</span></div><ul id={listId} role="listbox" aria-label={`${label} airport suggestions`}>{items.map((item,i)=><li key={item.ident} id={`${listId}-${i}`} role="option" aria-selected={i===highlight} aria-disabled={item.type==='closed'} className={i===highlight?'highlighted':''} onPointerDown={e=>e.preventDefault()} onMouseEnter={()=>setHighlight(i)} onClick={()=>select(item)}><span className="airport-result-code">{item.code}</span><span className="airport-result-copy"><strong>{item.name}</strong><small>{item.municipality && `${item.municipality}, `}{item.country_name} · {item.scheduled_service?'Scheduled service':item.type.replaceAll('_',' ')}</small></span></li>)}</ul>{!items.length&&!loading&&<p className="airport-no-results">{error||'No airport matches. Try its city, English name, IATA or ICAO code.'}</p>}<div className="airport-dropdown-footer">Reference data only · does not imply flight availability</div></div>}
  </div>;
}
