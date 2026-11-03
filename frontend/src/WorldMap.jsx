import { useMemo } from 'react';
import { geoNaturalEarth1, geoPath, geoGraticule10, geoInterpolate } from 'd3-geo';
import { feature } from 'topojson-client';
import topology from 'world-atlas/countries-110m.json';

export default function WorldMap({ airports=[] }) {
  const { projection, path, countries } = useMemo(() => {
    const projection = geoNaturalEarth1().scale(178).translate([500, 258]);
    return { projection, path: geoPath(projection), countries: feature(topology, topology.objects.countries).features };
  }, []);
  const points=airports.map(a=>[a.longitude,a.latitude]);
  return <svg viewBox="0 0 1000 500" className="world-map" role="img" aria-label={airports.length?`Flight route: ${airports.map(a=>a.code).join(' to ')}`:'Loading selected airport coordinates'}>
    <defs><radialGradient id="mapHalo"><stop stopColor="#163b63" stopOpacity=".33"/><stop offset="1" stopColor="#0b1420" stopOpacity="0"/></radialGradient><filter id="glow"><feGaussianBlur stdDeviation="3"/></filter></defs>
    <ellipse cx="510" cy="240" rx="480" ry="220" fill="url(#mapHalo)"/>
    <path d={path(geoGraticule10())} fill="none" stroke="#25374c" strokeOpacity=".25" strokeWidth=".5"/>
    {countries.filter(c => c.id !== '010').map((c,i) => <path key={`${c.id}-${i}`} d={path(c)} fill="#122439" stroke="#28415c" strokeWidth=".65"/>)}
    {points.slice(1).map((point,i)=>{
      const interpolate=geoInterpolate(points[i],point);
      const route={type:'LineString',coordinates:Array.from({length:65},(_,j)=>interpolate(j/64))};
      return <g key={`route-${i}`}><path d={path(route)} fill="none" stroke="#efba63" strokeWidth="6" opacity=".25" filter="url(#glow)"/><path d={path(route)} fill="none" stroke="#efba63" strokeWidth="1.7"/></g>;
    })}
    {airports.map((airport,i)=>{
      const [x,y]=projection(points[i]);
      const offset=i%2===0?-15:21;
      return <g key={`${airport.ident}-${i}`} className="route-node"><title>{airport.name} ({airport.code})</title><circle cx={x} cy={y} r="14" fill="#efba63" opacity=".15"/><circle cx={x} cy={y} r="8" fill="#efba63" opacity=".5" filter="url(#glow)"/><circle cx={x} cy={y} r="4" fill="#ffd583"/><text x={x+9} y={y+offset}>{airport.code} · {(airport.municipality || airport.name).toUpperCase()}</text></g>;
    })}
    <text x="32" y="464" className="map-caption">{airports.length?'SELECTED ITINERARY / AIRPORT REFERENCE COORDINATES':'LOADING ROUTE COORDINATES'}</text>
    <text x="968" y="464" textAnchor="end" className="map-caption">{airports.map(a=>a.code).join(' → ')}</text>
  </svg>;
}
