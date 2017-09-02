#!/usr/bin/python
"""
wawaGeoScraper.py

This script rips all Wawa location data hidden behind the restrictive store locator found here:
     https://www.wawa.com/about/locations/store-locator

The user must provide a connection string to PostgreSQL, and the name of the table to be created, following the
schema.name format.

Note: You will notice that I enter all the values into the database table (other than NULLs) surrounded with
      single quotes. This is because all of these datatypes can be entered that way. This saves me time by not having
      to quote only text and dates for valid sql statements.

For this to work correctly, the PostGIS extension for PostgreSQL must be installed with the user's version of the
software.

This is free, open source software.
License: https://www.gnu.org/licenses/gpl-3.0.en.html

Code by Connor Hornibrook (c) 2017
"""
import urllib2
import json
import psycopg2
import sys
import re
from progress.bar import Bar

REQUEST_URL = "https://www.wawa.com/Handlers/LocationByLatLong.ashx?limit={limit}&lat={y}&long={x}"
LAT_INCREMENTS = .072463768115942  # the approximate value of 5 miles in decimal degrees for latitude
SEARCH_RADIUS = 5  # miles

# various JSON tags and tag info that deserves special attention in the code
LOCATIONS_JSON_KEY = "locations"
ORDERED_JSON_ADDRESS_TAGS = ["zip", "city", "state", "address"]
AMENITIES_TAG = "amenities"
FUEL_BOOLEAN_TAG = "fuel"
FUEL_PRICES_TAG = "fuelTypes"
INDIVIDUAL_FUEL_PRICES_TAG = "price"
UNIQUE_ID_TAG = "locationID"
UNLEADED_INDEX, PLUS_INDEX, PREMIUM_INDEX = 0, 1, 2
JSON_COORD_TAG = "loc"
JSON_LAT_INDEX, JSON_LONG_INDEX = 0, 1
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

# This regex tests the syntactical validity of the user's input schema.tableName combination.
DB_TABLE_REGEX = r"[_a-zA-Z]+([_a-zA-Z]*\d*)*[.][_a-zA-Z]+([_a-zA-Z]*\d*)*"

# Needed number of user arguments
NEEDED_NUM_ARGS = 3


def quotify(value):
	"""
	Time saver function to put single quotes around a value. I wrapped all values in single quotes to simplify the
	SQL data entry. All data types can be wrapped in single quotes, so this avoids the need to check that dates,
	strings, timestamps, etc. are wrapped in quotes before "INSERT" statements are parsed.

	:param value: Any value
	:return: A stringified version of the value, surrounded by single quotes
	"""
	return "'" + str(value) + "'"


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
	return False if re.match(pattern, input_table) is None else True


if __name__ == "__main__":

	# validate and retrieve input
	if len(sys.argv) != NEEDED_NUM_ARGS:
		print "Not enough arguments input by the user!"
		sys.exit(1)
	connectionStr, tableName = sys.argv[1], sys.argv[2]

	# validate the format of the input PostgreSQL table name
	if not validate_postgres_table(tableName):
		print "Invalid table name input! ex) schema.table (must follow proper syntax rules)"
		sys.exit(1)

	# connect to db
	connection = None
	try:
		connection = psycopg2.connect(connectionStr)
	except psycopg2.OperationalError:
		print "Could not connect using this connection string!"
		sys.exit(1)
	cursor = connection.cursor()

	# drop existing table (if there is one) and create a new empty one
	cursor.execute("DROP TABLE IF EXISTS {0};".format(tableName))
	sql = "CREATE TABLE {0} (\n".format(tableName)
	for field in HEADER + ["geom"]:  # add a geometry field to the header list
		fieldType = FIELD_TYPES[field]
		sql += "{0} {1},\n".format(field, fieldType)
	sql = sql[:-2] + ");"

	# execute the parsed sql that creates the table, add a geometry column
	cursor.execute(sql)
	insertFormat = "INSERT INTO {0}({1}) VALUES (".format(tableName, ", ".join(HEADER + ["geom"]))

	# create the grid using bounding boxes for Florida and the Mid Atlantic region
	grid = create_grid(MID_ATL_BOX)
	grid.extend(create_grid(FL_BOX))

	# create a progress bar for the cmd line
	bar = Bar("Coordinate Pairs", max=len(grid))

	# go through each point in the grid
	for coordinatePair in grid:

		# parse the url that grabs the json data and read it
		goOn = False
		testURL = REQUEST_URL.format(x=coordinatePair[0], y=coordinatePair[1], limit=50)
		response = None

		# If an HTTPError 500 happens, repeat until it works (this rarely happens and this solution has worked so far)
		while not goOn:
			try:
				response = urllib2.urlopen(testURL)
				goOn = True
			except urllib2.HTTPError:
				pass

		# render the json and grab only the location data we need
		locations = json.load(response)[LOCATIONS_JSON_KEY]

		# iterate through the Wawa locations
		for location in locations:

			# this will be our new row in the database table, in the same order as the header list
			newRow = []

			# boolean indicating whether or not this wawa sells gas
			sellsGas = location[AMENITIES_TAG][FUEL_BOOLEAN_TAG]

			for tag in ORDERED_JSON_TAGS:

				# grab the value associated with this tag
				rawData = location[tag]

				# grab all the address data
				if tag == "addresses":
					addressInfo = parse_address_info(rawData)
					locationInfo = [addressInfo[0], addressInfo[1], addressInfo[2], addressInfo[3],
					                addressInfo[4][0], addressInfo[4][1]]
					newRow.extend(locationInfo)

				# similarly, we have to treat gas prices as a special case as well, as the individual components are
				# associated with the "fuelTypes" tag
				elif tag == FUEL_PRICES_TAG:
					if sellsGas:
						newRow.extend(parse_fuel_info(rawData))
					else:
						newRow.extend(["'0'", "NULL", "NULL", "NULL"])

				# Turn python type True into a '1' or '0' for entry in PostgreSQL. This step is probably not needed,
				# but it is standard with my preferred SQL syntax style.
				elif tag in BOOLEAN_TAGS:
					if rawData:
						newRow.append("'1'")
					else:
						newRow.append("'0'")

				# all other values can be taken as is, surrounded by single quotes
				else:
					if type(rawData) is str:
						escapeApost = rawData.replace("'", "''")
						newRow.append(quotify(escapeApost))
					else:
						newRow.append(quotify(rawData))

			thisSQL = insertFormat + ", ".join(newRow)
			geometry = "(SELECT ST_SetSRID(ST_Point({0}, {1}), 4326))".format(newRow[LONGITUDE_HEADER_INDEX],
			                                                                  newRow[LATITUDE_HEADER_INDEX])
			thisSQL += ", {0});".format(geometry)

			# Add entry to database only if unique key isn't already there. This is where we avoid duplicates that may
			# have resulted from overlapping search areas in our grid.
			try:
				cursor.execute(thisSQL)
				connection.commit()
			except psycopg2.IntegrityError:
				connection.rollback()  # rollback bad transaction

		# increment the progress bar object
		bar.next()
	# end the progress bar
	bar.finish()

	# commit changes and release possible memory locks
	connection.commit()
	connection.close()
	del connection, cursor
	print "Finished."
