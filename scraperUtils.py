#!/usr/bin/python
"""
scraperUtils.py

Various constants and functions used in the tools of this repository.

This is free, open source software.
License: https://www.gnu.org/licenses/gpl-3.0.en.html

Code by Connor Hornibrook (c) 2017
"""

# various constants
LAT_INCREMENTS = .072463768115942  # the approximate value of 5 miles in decimal degrees for latitude
SEARCH_RADIUS = 5  # miles

# Various indexes
UNLEADED_INDEX, PLUS_INDEX, PREMIUM_INDEX = 0, 1, 2
JSON_LAT_INDEX, JSON_LONG_INDEX = 0, 1

# This regex tests the syntactical validity of the user's input schema.tableName combination.
DB_TABLE_REGEX = r"[_a-zA-Z]+([_a-zA-Z]*\d*)*[.][_a-zA-Z]+([_a-zA-Z]*\d*)*"

# The URL
LOC_REQUEST_URL = "https://www.wawa.com/Handlers/LocationByLatLong.ashx?limit={limit}&lat={y}&long={x}"
STORENUM_REQUEST_URL = "https://www.wawa.com/Handlers/LocationByStoreNumber.ashx?storeNumber={storeNum}"

# various JSON tags and tag info that deserves special attention in the code
INDIVIDUAL_FUEL_PRICES_TAG = "price"
JSON_COORD_TAG = "loc"
LOCATIONS_JSON_KEY = "locations"
ORDERED_JSON_ADDRESS_TAGS = ["zip", "city", "state", "address"]
AMENITIES_TAG = "amenities"
FUEL_BOOLEAN_TAG = "fuel"
FUEL_PRICES_TAG = "fuelTypes"
UNIQUE_ID_TAG = "locationID"
ORDERED_JSON_TAGS = ["locationID", "objectID", "hasMenu", "areaManager", "open24Hours", "addresses", "regionalDirector",
                     "telephone", "isActive", "storeName", "lastUpdated", "storeNumber", "storeOpen", "storeClose",
                     FUEL_PRICES_TAG]
BOOLEAN_TAGS = ["hasMenu", "isActive", "open24Hours"]

# The order of the fields that will be present in the database table, sans the geometry column that will be added later
HEADER = ["locationID", "objectID", "hasMenu", "areaManager", "open24Hours", "address", "city", "state", "zip",
          "longitude", "latitude", "regionalDirector", "telephone", "isActive", "storeName", "lastUpdated",
          "storeNumber", "storeOpen", "storeClose", "hasFuel", "unleadedPrice", "plusPrice", "premiumPrice"]
LONGITUDE_HEADER_INDEX, LATITUDE_HEADER_INDEX = 9, 10

# The PostgreSQL data types associated with the previously mentioned database table fields
FIELD_TYPES = {"locationID": "INT PRIMARY KEY", "objectID": "TEXT", "hasMenu": "BOOLEAN", "areaManager": "TEXT",
               "open24Hours": "BOOLEAN", "address": "TEXT", "longitude": "DOUBLE PRECISION",
               "latitude": "DOUBLE PRECISION", "regionalDirector": "TEXT", "telephone": "TEXT", "isActive": "BOOLEAN",
               "storeName": "TEXT", "lastUpdated": "TIMESTAMP", "storeNumber": "INT", "storeOpen": "TIME",
               "storeClose": "TIME", "hasFuel": "BOOLEAN", "unleadedPrice": "DOUBLE PRECISION",
               "plusPrice": "DOUBLE PRECISION", "premiumPrice": "DOUBLE PRECISION", "geom": "GEOMETRY",
               "city": "TEXT", "state": "TEXT", "zip": "TEXT"}

# These bounding boxes cover the entire state of Florida and the Mid-Atlantic region, respectively.
# Bounding boxes measured using http://boundingbox.klokantech.com/
# Wawas are only in NJ, PA, MD, DE, VA, and FL
FL_BOX = ((-87.7368164063, 24.1066471792), (-79.9584960937, 31.1281992991))
MID_ATL_BOX = ((-83.583984375, 36.2797072052), (-73.6962890625, 42.2610491621))


def quotify(value):
	"""
	Time saver function to put single quotes around a value. I wrapped all values in single quotes to simplify the
	SQL data entry. All data types can be wrapped in single quotes, so this avoids the need to check that dates,
	strings, timestamps, etc. are wrapped in quotes before "INSERT" statements are parsed.

	:param value: Any value
	:return: A stringified version of the value, surrounded by single quotes
	"""
	return "'" + str(value) + "'"


# def validate_connection_string(input_cnxn):
# 	"""
# 	If the input connection string is valid, this returns a psycopg2 Connection object,
# 	else it throws an exception.
#
# 	:param input_cnxn: A user-input connection string
# 	:return: a psycopg2 Connection object
# 	"""
# 	from psycopg2 import connect, OperationalError
#
# 	try:
# 		out_cnxn = connect(input_cnxn)
# 		return out_cnxn
# 	except OperationalError:
# 		raise OperationalError


def create_grid(bounding_box):
	"""
	Creates a grid of equally spaced coordinate pairs in a provided bounding box

	:param bounding_box: A pair of points that represent the upper left and lower right coordinates of a bounding box
	:return: A list of points: [(x1, y1), (x2, y2),..., (xn, yn)]
	"""
	lowerLeft, upperRight = bounding_box[0], bounding_box[1]
	maxX, maxY, minX, minY = upperRight[0], upperRight[1], lowerLeft[0], lowerLeft[1]
	points = []
	currentX, currentY = minX, minY

	while currentY < maxY:
		while currentX < maxX:
			points.append((currentX, currentY))
			currentX += LAT_INCREMENTS
		currentY += LAT_INCREMENTS
		currentX = minX

	return points


def parse_fuel_info(input_data):
	"""
	Parses fuel info from the input json data
	:param input_data: json data that contains info about a Wawa's fuel prices and types
	:return: a list of gas prices [unleadedPrice, plusPrice, premiumPrice]
	"""
	unleadedPrice = input_data[UNLEADED_INDEX][INDIVIDUAL_FUEL_PRICES_TAG]
	plusPrice = input_data[PLUS_INDEX][INDIVIDUAL_FUEL_PRICES_TAG]
	premiumPrice = input_data[PREMIUM_INDEX][INDIVIDUAL_FUEL_PRICES_TAG]
	return ["'1'", quotify(unleadedPrice), quotify(plusPrice), quotify(premiumPrice)]


def parse_address_info(input_data):
	"""
    Parses address info from the input json data
    :param input_data: json data that contains info about a Wawa's address and coordinates.
    :return: a tuple containing the full address and the coordinates ex) (address, (long, lat))
    """

	rawStreetJSON, rawCoordJSON = input_data[0], input_data[1]
	coordinates = rawCoordJSON[JSON_COORD_TAG]
	coordinates = (quotify(coordinates[JSON_LONG_INDEX]), quotify(coordinates[JSON_LAT_INDEX]))
	zipCode, city, state, address = rawStreetJSON["zip"], rawStreetJSON["city"], rawStreetJSON["state"], \
	                                rawStreetJSON["address"]
	address = address.replace("'", "''")

	# fullAddress = "{0} {1}, {2} {3}".format(address, city, state, zipCode)
	# fullAddress = fullAddress.replace("'", "''")

	return quotify(address), quotify(city), quotify(state), quotify(zipCode), coordinates


def validate_postgres_table(input_table, pattern=DB_TABLE_REGEX):
	"""
	Validates a PostgreSQL schema.tableName combo
	:param input_table: the tested table
	:param pattern: the regex pattern used to test validity (defaulted to constant value)
	:return: whether or not the tableName was valid
	"""
	from re import match
	return False if match(pattern, input_table) is None else True
