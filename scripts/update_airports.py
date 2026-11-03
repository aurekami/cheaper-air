#!/usr/bin/env python3
"""Refresh the bundled public-domain OurAirports reference snapshot."""
import csv
import gzip
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / 'backend/src/cheaper_air/data'
BASE_URL = 'https://davidmegginson.github.io/ourairports-data/'
COLUMNS = ['ident', 'iata_code', 'name', 'municipality', 'country', 'country_name',
           'type', 'scheduled_service', 'latitude', 'longitude']


def read_csv(name):
    with urlopen(BASE_URL + name, timeout=60) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode('utf-8'))))


def main():
    countries = {r['code']: r['name'] for r in read_csv('countries.csv')}
    rows = [[r['ident'], r['iata_code'], r['name'], r['municipality'], r['iso_country'],
             countries.get(r['iso_country'], r['iso_country']), r['type'], r['scheduled_service'] == 'yes',
             float(r['latitude_deg']), float(r['longitude_deg'])] for r in read_csv('airports.csv')]
    if len(rows) < 50000:
        raise ValueError('Unexpectedly small dataset; preserve the existing snapshot')
    data = gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0)
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'airports.json.gz').write_bytes(data)
    metadata = {'source': 'OurAirports', 'source_url': 'https://ourairports.com/data/',
                'downloaded_at': datetime.now(timezone.utc).date().isoformat(), 'license': 'Public domain',
                'records': len(rows), 'sha256': hashlib.sha256(data).hexdigest(), 'columns': COLUMNS}
    (ROOT / 'airports-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f"Updated {len(rows):,} airport records. Restart the backend to load them.")


if __name__ == '__main__':
    main()
