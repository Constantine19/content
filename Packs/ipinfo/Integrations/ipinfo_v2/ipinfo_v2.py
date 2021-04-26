from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from CommonServerUserPython import *  # noqa

import requests
import traceback
from typing import Dict, Any

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()  # pylint: disable=no-member


class Client(BaseClient):
    def __init__(self, api_key: str, base_url: str, verify_certificate: bool, proxy: bool,
                 reliability: DBotScoreReliability):
        """
        Client to use in the IPinfo integration. Uses BaseClient
        """
        super().__init__(base_url=base_url, proxy=proxy, verify=verify_certificate)
        self.api_key = api_key
        self.reliability = reliability

    def _url_suffix(self, ip: str) -> str:
        api_key_in_url = f'?token={self.api_key}' if self.api_key else ''
        return f'{ip}/json{api_key_in_url}'

    def ipinfo_ip(self, ip: str) -> Dict[str, Any]:
        return self._http_request(method='GET', url_suffix=self._url_suffix(ip=ip))


def test_module(client: Client) -> str:
    """Tests IPinfo by sending a query on 8.8.8.8"""
    client.ipinfo_ip('8.8.8.8')
    return 'ok'  # on any failure, an exception is raised


#

def ipinfo_ip_command(client: Client, ip: str) -> List[CommandResults]:
    response = client.ipinfo_ip(ip)
    return parse_results(ip, response, client.reliability)


def parse_results(ip: str, raw_result: Dict[str, Any], reliability: DBotScoreReliability) -> List[CommandResults]:
    command_results = []

    # default values
    asn = as_owner = None
    feed_related_indicators = []

    if raw_result:
        hostname = raw_result.get('hostname')
        feed_related_indicators.append(
            Common.FeedRelatedIndicators(hostname,
                                         FeedIndicatorType.URL if urlRegex.find(hostname)
                                         else FeedIndicatorType.Domain))
        if 'asn' in raw_result:
            asn = demisto.get(raw_result, 'asn.asn')
            as_owner = demisto.get(raw_result, 'asn.name')
            as_domain = demisto.get(raw_result, 'asn.domain')

            if as_domain:
                feed_related_indicators.append(Common.FeedRelatedIndicators(as_domain, FeedIndicatorType.Domain))

        elif 'org' in raw_result:
            org = raw_result.get('org', '')
            org_parts = org.split(' ')
            if ' ' in org:
                asn, as_owner = org_parts[0], ' '.join(org_parts[1:])

        organization = {
            'Name': demisto.get(raw_result, 'company.name'),
            'Type': demisto.get(raw_result, 'company.type')
        } if 'company' in raw_result else None

        company_domain = demisto.get(raw_result, 'company.domain')
        if company_domain is not None:
            feed_related_indicators.append(Common.FeedRelatedIndicators(company_domain, FeedIndicatorType.Domain))

        abuse = {
            'Address': demisto.get(raw_result, 'abuse.address'),
            'Country': demisto.get(raw_result, 'abuse.country'),
            'Name': demisto.get(raw_result, 'abuse.name'),
            'Network': demisto.get(raw_result, 'abuse.network'),
            'Phone': demisto.get(raw_result, 'abuse.phone'),
            'Email': demisto.get(raw_result, 'abuse.email')
        } if 'abuse' in raw_result else None

        tags = []
        for (tag_path, tag_name) in (('privacy.hosting', 'hosting'),
                                     ('privacy.proxy', 'proxy'),
                                     ('privacy.tor', 'tor'),
                                     ('privacy.vpn', 'vpn')):
            if demisto.get(raw_result, tag_path):
                tags.append(tag_name)

        city = raw_result.get('city')
        region = raw_result.get('region')
        postal = raw_result.get('postal')
        country = raw_result.get('country')

        description = ', '.join(filter(None, [city, region, postal, country]))

        # parses geolocation
        lat = lon = ''
        loc = raw_result.get('loc', '')  # empty string as default on purpose,
        if ',' in loc:
            coordinates = loc.split(',')
            lat, lon = float(coordinates[0]), float(coordinates[1])

        entry_context = {'Address': raw_result.get('ip'),
                         'Hostname': hostname,
                         'ASN': asn,
                         'ASOwner': as_owner,
                         'Tags': tags,
                         'Organization': organization,
                         'Geo': {'Location': loc, 'Country': country, 'Description': description},
                         'Registrar': {'Abuse': abuse} if abuse else None}

        outputs_key_field = 'Address'  # marks the ip address

        indicator = Common.IP(
            ip=ip,
            dbot_score=Common.DBotScore(indicator='ip',
                                        indicator_type=DBotScoreType.IP,
                                        integration_name='IPinfo_v2',
                                        reliability=reliability,
                                        score=Common.DBotScore.NONE),
            asn=asn,
            hostname=hostname,
            feed_related_indicators=feed_related_indicators,
            geo_latitude=str(lat) if lat else None,
            geo_longitude=str(lon) if lon else None,
            geo_description=description or None,
            geo_country=country,
            tags=','.join(tags))

        command_results.append(CommandResults(
            readable_output=tableToMarkdown(f'IPinfo results for {ip}', raw_result),
            raw_response=raw_result,
            outputs_prefix='IPinfo.IP',
            outputs=entry_context,
            outputs_key_field=outputs_key_field,
            indicator=indicator))

        if lat and lon:
            map_output = CommandResults(raw_response={'lat': lat, 'lng': lon},
                                        entry_type=EntryType.MAP_ENTRY_TYPE,
                                        outputs_key_field=outputs_key_field,
                                        indicator=indicator)
            command_results.append(map_output)

    return command_results


def main() -> None:
    """main function, parses params and runs command functions"""

    params = demisto.params()
    args = demisto.args()
    command = demisto.command()

    proxy = params.get('proxy') or False
    api_key = demisto.get(params, 'credentials.password') or ''
    insecure = params.get('insecure') or False
    base_url = params.get('base_url') or "https://ipinfo.io"

    demisto.debug(f'Command being called is {command}')

    reliability = params.get('integrationReliability')
    if DBotScoreReliability.is_valid_type(reliability):
        reliability = DBotScoreReliability.get_dbot_score_reliability_from_str(reliability)
    else:
        raise Exception("Please provide a valid value for the Source Reliability parameter.")

    try:
        client = Client(api_key=api_key,
                        verify_certificate=insecure,
                        proxy=proxy,
                        base_url=base_url,
                        reliability=reliability)

        if command == 'test-module':
            return_results(test_module(client))

        elif command == 'ip':
            ip_command = ipinfo_ip_command(client, **args)
            return_results(ip_command)

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute {command} command.'
                     f'\nError:\n{str(e)}')


if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
