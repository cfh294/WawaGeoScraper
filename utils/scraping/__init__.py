"""
scraping
the utility functions for the actual web scraping
"""

import ssl
import datetime
import requests
import re

# this is the endpoint that my new version of this program will
# abuse with possible store ids. this is a much more reliable "darts at the wall"
# technique than the previous location-based one
QUERY_URL = "https://www.wawa.com/Handlers/LocationByStoreNumber.ashx"

# from testing, I have confirmed certain "series" of store IDs
# 0000 series are all old stores in PA, NJ, MD, DE, and VA
# 5000 series are all stores in FL
# 8000 series are all new stores in PA, NJ, MD, DE, and VA
POSSIBLE_STORE_NUMS = list(range(5000, 6000))
POSSIBLE_STORE_NUMS.extend(list(range(0, 1000)))
POSSIBLE_STORE_NUMS.extend(list(range(8000, 9000)))

# currently only tracking these gas types to keep a consistent csv schema.
# other types are not consistent across all wawas
GAS_TYPES = ["diesel", "plus", "unleaded", "premium"]


def parse_gas_prices(in_location):
    """
    Breaks open the json for the gas prices
    :param in_location: The Wawa location we are looking at (dict)
    :return:            The gas price info                  (dict)
    """
    out_data = {}
    try:
        fuel_data = in_location["fuelTypes"]
        for ft in fuel_data:
            lowered = ft["description"].lower()
            if lowered in GAS_TYPES:
                out_data[lowered + "_price"] = ft["price"]

    # no gas sold at this Wawa
    except KeyError:
        for gt in GAS_TYPES:
            out_data[gt + "_price"] = ""
    return out_data


def camel_to_underscore(in_string):
    """
    Basic function that converts a camel-cased word to use underscores
    :param in_string: The camel-cased string  (str)
    :return:          The underscore'd string (str)
    """
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', in_string)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def parse_amenities(in_location):
    """
    Breaks open the json for the amenities offered at the Wawa location
    :param in_location: The Wawa location (dict)
    :return:            The amenity info  (dict)
    """
    out_data = {}
    for amenity, value in in_location["amenities"].items():
        out_data["has_" + camel_to_underscore(amenity).lower()] = value
    return out_data


def get_addresses(in_location):
    """
    Parses info for the Wawa address and coordinates
    :param in_location: The Wawa location                (dict)
    :return:            The address and coordincate info (dict)
    """
    friendly = in_location["addresses"][0]
    physical = in_location["addresses"][1]

    out_friendly = {
        "address": friendly["address"],
        "city": friendly["city"],
        "state": friendly["state"],
        "zip": friendly["zip"]
    }

    out_physical = {
        "longitude": physical["loc"][1],
        "latitude": physical["loc"][0],
    }

    return {"address": out_friendly, "coordinates": out_physical}


def get_wawa_data(limit=None):
    """
    Hits the store number url endpoint to pull down Wawa locations and
    parse each one's information. We don't know the store numbers as there
    is not list of store numbers. Through testing I was able to narrow down
    "series" of store numbers, so we iterate through ranges of possible
    store numbers, skipping any 404 errors (invalid store id responses
    returned by url calls).
    :param limit: A cap on the number of Wawa results returned (int) (optional)
    :return:      Parsed Wawa information (list<dict>)
    """
    ssl._create_default_https_context = ssl._create_unverified_context
    output = []

    for i in POSSIBLE_STORE_NUMS:
        response = requests.get(QUERY_URL, params={"storeNumber": i})

        if response.status_code != 404:
            location = response.json()
            geographic_data = get_addresses(location)
            address = geographic_data["address"]
            coordinates = geographic_data["coordinates"]
            gas_prices = parse_gas_prices(location)
            amenities  = parse_amenities(location)
            this_location_output = {
                "has_menu": location["hasMenu"],
                "last_updated": datetime.datetime.strptime(location["lastUpdated"], "%m/%d/%Y %I:%M %p"),
                "location_id": location["locationID"],
                "open_24_hours": location["open24Hours"],
                "regional_director": location["regionalDirector"],
                "store_close": location["storeClose"],
                "store_name": location["storeName"],
                "store_number": location["storeNumber"],
                "store_open": location["storeOpen"],
                "telephone": location["telephone"]
            }

            this_location_output = {**this_location_output, **address}
            this_location_output = {**this_location_output, **coordinates}
            this_location_output = {**this_location_output, **gas_prices}
            this_location_output = {**this_location_output, **amenities}

            output.append(this_location_output)
            if limit and len(output) == limit:
                break
    return output
