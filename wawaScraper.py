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
# Import standard libraries
import urllib2
import json
import psycopg2
import sys
import os
from progress.bar import Bar

# Import all our needed constants and functions
from scraperUtils import validate_postgres_table, parse_fuel_info, parse_address_info, quotify
from scraperUtils import HEADER, FIELD_TYPES, LOC_REQUEST_URL, LOCATIONS_JSON_KEY, AMENITIES_TAG
from scraperUtils import FUEL_PRICES_TAG, ORDERED_JSON_TAGS, FUEL_BOOLEAN_TAG, BOOLEAN_TAGS
from scraperUtils import LONGITUDE_HEADER_INDEX, LATITUDE_HEADER_INDEX, get_clipped_grid, LOCATION_ID_INDEX

# Needed number of user arguments
NEEDED_NUM_ARGS = 3

if __name__ == "__main__":

	# the path to the directory that holds this project
	projectRoot = os.path.dirname(os.path.abspath(__file__))

	# validate and retrieve input
	if len(sys.argv) != NEEDED_NUM_ARGS:
		print "Invalid number of arguments input by the user!"
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

	# create the table, if needed
	sql = "CREATE TABLE IF NOT EXISTS {0} (\n".format(tableName)
	for field in HEADER + ["geom"]:  # add a geometry field to the header list
		fieldType = FIELD_TYPES[field]
		sql += "{0} {1},\n".format(field, fieldType)
	sql = sql[:-2] + ");"

	# execute the parsed sql that creates the table, add a geometry column
	cursor.execute(sql)
	insertFormat = "INSERT INTO {0}({1}) VALUES (".format(tableName, ", ".join(HEADER + ["geom"]))

	# create the grid using bounding boxes for Florida and the Mid Atlantic region
	# see: get_clipped_grid() in scraperUtils.py
	grid = get_clipped_grid()

	# create a progress bar for the cmd line
	bar = Bar("Coordinate Pairs", max=len(grid))
	storeNumbers = set()

	# go through each point in the grid
	for coordinatePair in grid:

		# parse the url that grabs the json data and read it
		goOn = False
		testURL = LOC_REQUEST_URL.format(x=coordinatePair[0], y=coordinatePair[1], limit=50)
		response = None

		# If an HTTPError 500 happens, repeat until it works (this rarely happens and this solution has worked so far)
		while not goOn:
			try:
				response = urllib2.urlopen(testURL)
				goOn = True
			except urllib2.HTTPError:
				pass
			except urllib2.URLError:
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
			except psycopg2.IntegrityError:
				connection.rollback()  # rollback bad transaction

				# update the data
				sql = "UPDATE {0} SET\n".format(tableName)
				for index, fieldName in enumerate(HEADER):
					sql += "{0}={1},\n".format(fieldName, newRow[index])
				sql = sql[:-2] + "\nWHERE {0}={1};".format(HEADER[LOCATION_ID_INDEX], newRow[LOCATION_ID_INDEX])

				try:
					cursor.execute(sql)
				except psycopg2.ProgrammingError:
					print "\nSQL Error:\n{0}".format(sql)
					sys.exit(1)
			storeNumbers.add(newRow[LOCATION_ID_INDEX])

		# increment the progress bar object
		bar.next()
	# end the progress bar
	bar.finish()

	# Wawa doesn't use this field, so we will. All of these are "active" store (as in, open). Set them all to true.
	cursor.execute("UPDATE {0} SET isactive='t';".format(tableName))

	# set inactive wawas to false
	doneNums = ",".join(storeNumbers)
	cursor.execute("UPDATE {0} SET isactive='f' WHERE locationid NOT IN ({1});".format(tableName, doneNums))

	# commit changes and release possible memory locks
	connection.commit()
	connection.close()
	del connection, cursor
	print "Finished."
