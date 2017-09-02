import urllib2
import json
import psycopg2
import sys
from math import pi, cos
from progress.bar import Bar

REQUEST_URL = "https://www.wawa.com/Handlers/LocationByLatLong.ashx?limit={limit}&lat={y}&long={x}"
LAT_INCREMENTS = .072463768115942  # the approximate value of 5 miles in decimal degrees for latitude
LONG_AT_EQUATOR_IN_MILES = 69.172
SEARCH_RADIUS = 5  # miles

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
TEST_COORDS = [(-74.4057, 40.0583), (-81.5158, 27.6648), (-75.5277, 38.9108)]

ORDERED_JSON_TAGS = ["locationID", "objectID", "hasMenu", "areaManager", "open24Hours", "addresses", "regionalDirector",
                     "telephone", "isActive", "storeName", "lastUpdated", "storeNumber", "storeOpen", "storeClose",
                     FUEL_PRICES_TAG]
BOOLEAN_TAGS = ["hasMenu", "isActive", "open24Hours"]
HEADER = ["locationID", "objectID", "hasMenu", "areaManager", "open24Hours", "address", "city", "state", "zip",
          "longitude", "latitude", "regionalDirector", "telephone", "isActive", "storeName", "lastUpdated",
          "storeNumber", "storeOpen", "storeClose", "hasFuel", "unleadedPrice", "plusPrice", "premiumPrice"]

LONGITUDE_HEADER_INDEX, LATITUDE_HEADER_INDEX = 9, 10

FIELD_TYPES = {"locationID": "INT PRIMARY KEY", "objectID": "TEXT", "hasMenu": "BOOLEAN", "areaManager": "TEXT",
               "open24Hours": "BOOLEAN", "address": "TEXT", "longitude": "DOUBLE PRECISION",
               "latitude": "DOUBLE PRECISION", "regionalDirector": "TEXT", "telephone": "TEXT", "isActive": "BOOLEAN",
               "storeName": "TEXT", "lastUpdated": "TIMESTAMP", "storeNumber": "INT", "storeOpen": "TIME",
               "storeClose": "TIME", "hasFuel": "BOOLEAN", "unleadedPrice": "DOUBLE PRECISION",
               "plusPrice": "DOUBLE PRECISION", "premiumPrice": "DOUBLE PRECISION", "geom": "GEOMETRY",
               "city": "TEXT", "state": "TEXT", "zip": "TEXT"}


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


def create_grid(bounding_box):
	"""
	Creates a grid of equally spaced coordinate pairs in a provided bounding box

	:param bounding_box: A pair of points that represent the upper left and lower right coordinates of a bounding box
	:return:
	"""

	lowerLeft, upperRight = bounding_box[0], bounding_box[1]
	maxX, maxY, minX, minY = upperRight[0], upperRight[1], lowerLeft[0], lowerLeft[1]
	points = []
	currentX, currentY = minX, minY

	while currentY < maxY:
		while currentX < maxX:
			points.append((currentX, currentY))
			# fiveMiles = SEARCH_RADIUS / (cos(currentY) * LONG_AT_EQUATOR_IN_MILES)
			currentX += LAT_INCREMENTS
		currentY += LAT_INCREMENTS
		currentX = minX

	# while currentX < maxX:
	# 	while currentY < maxY:
	# 		points.append((currentX, currentY))
	# 		currentY += LAT_INCREMENTS
	#
	# 	# calculate the increment value
	# 	currentX += space
	# 	currentY = minY
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


def main(connectionStr, tableName):

	# begin PostgreSQL work by grabbing system parameters
	# connect to db
	connection = psycopg2.connect(connectionStr)
	cursor = connection.cursor()

	# drop existing table (if there is one) and create a new empty one
	cursor.execute("DROP TABLE IF EXISTS {0};".format(tableName))
	sql = "CREATE TABLE {0} (\n".format(tableName)
	for field in HEADER + ["geom"]:  # add a geometry field to the header list
		fieldType = FIELD_TYPES[field]
		sql += "{0} {1},\n".format(field, fieldType)
	sql = sql[:-2] + ");"

	# execute the parsed sql that creates the table
	cursor.execute(sql)
	insertFormat = "INSERT INTO {0}({1}) VALUES (".format(tableName, ", ".join(HEADER + ["geom"]))

	# create the grid using bounding boxes for Florida and the Mid Atlantic region
	grid = create_grid(MID_ATL_BOX)
	grid.extend(create_grid(FL_BOX))
	outTable = []
	bar = Bar("Coordinate Pairs", max=len(grid))
	try:
		# go through each point in the grid
		for coordinatePair in grid:
			# parse the url that grabs the json data and read it
			goOn = False
			testURL = REQUEST_URL.format(x=coordinatePair[0], y=coordinatePair[1], limit=50)
			response = None
			while not goOn:
				try:
					response = urllib2.urlopen(testURL)
					goOn = True
				except urllib2.HTTPError:
					pass

			# render the json and grab only the location data we need
			locations = json.load(response)[LOCATIONS_JSON_KEY]
			newRows = []

			# iterate through the Wawa locations
			for location in locations:
				newRow = []
				sellsGas = location[AMENITIES_TAG][FUEL_BOOLEAN_TAG]

				for tag in ORDERED_JSON_TAGS:

					# grab the value associated with this tag
					rawData = location[tag]

					# parse the address, if needed, by combining the separate components (zip, state, city, etc. are
					# all separated in this returned json
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

			# 	# add the row to the list of rows for this point
			# 	newRows.append(newRow)
			# # add the new rows to to the overall list
			# outTable.extend(newRows)

			bar.next()
		bar.finish()

	except KeyboardInterrupt:
		pass

	# commit changes and release possible memory locks
	connection.commit()
	connection.close()
	del connection, cursor
	print "Finished."

if __name__ == "__main__":
	main(sys.argv[1], sys.argv[2])