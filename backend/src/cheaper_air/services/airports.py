"""Offline global airport reference data; this is not flight inventory."""
import gzip
import json
import re
import unicodedata
from functools import lru_cache
from importlib.resources import files


def normalize(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


class AirportCatalog:
    def __init__(self):
        root = files('cheaper_air').joinpath('data')
        self.metadata = json.loads(root.joinpath('airports-metadata.json').read_text())
        columns = self.metadata['columns']
        rows = json.loads(gzip.decompress(root.joinpath('airports.json.gz').read_bytes()))
        self.airports = []
        self.by_code = {}
        self.index = []
        for row in rows:
            airport = dict(zip(columns, row))
            airport['code'] = airport['iata_code'] if re.fullmatch(r'[A-Z]{3}', airport['iata_code']) else airport['ident']
            self.airports.append(airport)
            for code in (airport['code'], airport['ident']):
                existing = self.by_code.get(code)
                if existing is None or self.priority(airport) < self.priority(existing):
                    self.by_code[code] = airport
            text = normalize(' '.join(str(airport[k]) for k in ('code', 'ident', 'name', 'municipality', 'country', 'country_name')))
            self.index.append((airport, text))

    @staticmethod
    def priority(airport):
        return (airport['type'] == 'closed', not airport['scheduled_service'],
                {'large_airport': 0, 'medium_airport': 1, 'small_airport': 2}.get(airport['type'], 3), airport['name'])

    def get(self, code: str):
        return self.by_code.get(code.upper())

    def search(self, query: str, limit: int = 10):
        value = normalize(query.strip())
        # Local-language aliases supplement the worldwide reference, not its coverage.
        aliases = {'majami': 'miami', 'majamis': 'miami', 'majamį': 'miami', 'majamio': 'miami',
                   'vilnius': 'vilnius', 'londonas': 'london', 'londona': 'london', 'niujorkas': 'new york',
                   'niujorka': 'new york', 'varsuva': 'warsaw', 'varsuvos': 'warsaw', 'warszawa': 'warsaw', 'paryzius': 'paris', 'paryziu': 'paris', 'tokijas': 'tokyo', 'tokija': 'tokyo', 'tokijus': 'tokyo', 'tokiju': 'tokyo', 'tokijo': 'tokyo'}
        value = aliases.get(value, value)
        if not value:
            matches = [(a, text) for a, text in self.index if a['scheduled_service'] and a['type'] == 'large_airport']
        else:
            tokens = value.split()
            matches = [(a, text) for a, text in self.index if all(token in text for token in tokens)]
        # Metropolitan names can span municipalities in the reference data.
        metro_codes = {'tokyo': ('HND', 'NRT'), 'warsaw': ('WAW', 'WMI')}.get(value, ())
        found = {a['ident'] for a, _ in matches}
        for code in metro_codes:
            airport = self.get(code)
            if airport and airport['ident'] not in found:
                matches.append((airport, normalize(airport['name'])))
        matches.sort(key=lambda item: (0 if value and value in (normalize(item[0]['code']), normalize(item[0]['ident'])) else 1, *self.priority(item[0])))
        return [a for a, _ in matches[:limit]]


@lru_cache(maxsize=1)
def get_airport_catalog():
    return AirportCatalog()
