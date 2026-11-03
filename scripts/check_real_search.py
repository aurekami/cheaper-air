#!/usr/bin/env python3
"""Run one explicitly requested localization search using the configured provider key."""
import argparse
import asyncio
from datetime import datetime, timezone
from cheaper_air.config import Settings
from cheaper_air.domain.models import SearchCriteria
from cheaper_air.providers.errors import ProviderError
from cheaper_air.providers.serpapi import SerpApiProvider


def main():
    parser=argparse.ArgumentParser(description='One user-initiated SerpApi smoke search; may consume one API search credit.')
    parser.add_argument('--origin',default='VNO')
    parser.add_argument('--destination',required=True)
    parser.add_argument('--date',required=True)
    parser.add_argument('--country',default='LT')
    args=parser.parse_args()
    criteria=SearchCriteria(origin=args.origin,destination=args.destination,departure_date=args.date,
                            markets=[args.country],baseline_market=args.country,data_mode='REAL')
    if criteria.departure_date < datetime.now(timezone.utc).date():
        parser.error('Departure date must not be in the past.')
    async def run():
        try:
            observations,warnings,_=await SerpApiProvider(Settings().serpapi_api_key).search(criteria,datetime.now(timezone.utc))
        except ProviderError as error:
            print(f'{error.code}: {error}')
            return 1
        print(f'REAL source observations: {len(observations)}. Fare conditions unverified; savings unavailable.')
        for item in observations[:5]:
            print(f'{item.price.amount} {item.price.currency}: ' + ' / '.join(f'{s.origin}-{s.destination} {s.flight_number or ""}' for s in item.segments))
        for warning in warnings: print(warning)
        return 0
    raise SystemExit(asyncio.run(run()))


if __name__=='__main__':
    main()
