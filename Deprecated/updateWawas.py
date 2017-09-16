#!/usr/bin/python
"""
WARNING ------------ DEPRECATED ------------------
updateWawas.py

Script that updates Wawa info using HTTP Requests. User inputs a connection string and the name
of the table that was originally downloaded with wawaScraper.py

This is free, open source software.
License: https://www.gnu.org/licenses/gpl-3.0.en.html

Code by Connor Hornibrook (c) 2017
"""

# Import standard libraries
import urllib2
import json
import psycopg2
import sys
from progress.bar import Bar

# Import all our needed constants and functions
from scraperUtils import validate_postgres_table, parse_fuel_info, parse_address_info, quotify
from scraperUtils import HEADER, AMENITIES_TAG
from scraperUtils import FUEL_PRICES_TAG, ORDERED_JSON_TAGS, FUEL_BOOLEAN_TAG, BOOLEAN_TAGS
from scraperUtils import STORENUM_REQUEST_URL

# Script-specific constants
MIN_ARGS = 3
MAX_ARGS = 4
EXISTS_SQL = """
             SELECT EXISTS (
              SELECT *
              FROM information_schema.tables
              WHERE
              table_schema = '{0}' AND
              table_name = '{1}'
             );"""

if __name__ == "__main__":

	# check that a valid number of arguments is entered
	numArgs = len(sys.argv)
	if not(MIN_ARGS <= numArgs <= MAX_ARGS):
		print "Invalid number of arguments input by the user!"
		sys.exit(1)

	connectionString, tableName = sys.argv[1], sys.argv[2]
	locationIDField = sys.argv[3] if numArgs == MAX_ARGS else "locationid"

	locationIDFieldType = type(locationIDField)
	if locationIDFieldType is not str:
		print "Invalid field type input!\nNeeded: 'str', Given: '{0}'".format(str(locationIDFieldType))
		sys.exit(1)

	# validate the format of the input PostgreSQL table name
	if not validate_postgres_table(tableName):
		print "Invalid table name input! ex) schema.table (must follow proper syntax rules)"
		sys.exit(1)

	# validate the connection string
	connection = None

	try:
		connection = psycopg2.connect(connectionString)
	except psycopg2.OperationalError:
		print "Could not connect using this connection string!"
		sys.exit(1)
	cursor = connection.cursor()

	splitTable = tableName.split(".")
	schema, tableNameIso = splitTable[0], splitTable[1]

	# validate that the table exists
	validationSQL = EXISTS_SQL.format(schema, tableNameIso)
	cursor.execute(validationSQL)
	result = cursor.fetchone()[0]
	if result is not True:
		print "Table '{0}' does not exist in your database!".format(tableName)
		sys.exit(1)

	# grab the store numbers
	cursor.execute("SELECT {0} FROM {1};".format(locationIDField, tableName))
	storeNumbers = [int(row[0]) for row in cursor.fetchall()]

	# iterate through the store numbers
	bar = Bar("Stores", max=len(storeNumbers))
	fails = []
	for storeNumber in storeNumbers:

		# parse the url that grabs the json data and read it
		goOn = False
		testURL = STORENUM_REQUEST_URL.format(storeNum=storeNumber)
		response = None

		# If an HTTPError 500 happens, repeat until it works (this rarely happens and this solution has worked so far)
		gotData = False
		while not goOn:
			try:
				response = urllib2.urlopen(testURL)
				goOn = True
				gotData = True
			except urllib2.HTTPError as webError:

				# Wawa no longer open
				if webError.code == 404:
					fails.append(str(storeNumber))
					goOn = True

				# Internal server error, retry
				elif webError.code == 500:
					pass

				# Other error, fail out the program
				else:
					print "\nError:\n{0}".format(str(webError))
					sys.exit(1)

		# Only do work if there was no error 404
		if gotData:

			# render the json and grab only the location data we need
			storeJSON = json.load(response)

			# this will be our updated data for this location
			updatedData = []

			# boolean indicating whether or not this wawa sells gas
			sellsGas = storeJSON[AMENITIES_TAG][FUEL_BOOLEAN_TAG]
			sql = "UPDATE {0} SET\n".format(tableName)

			for tag in ORDERED_JSON_TAGS:

				# grab the value associated with this tag
				rawData = storeJSON[tag]

				# grab all the address data
				if tag == "addresses":
					addressInfo = parse_address_info(rawData)
					locationInfo = [addressInfo[0], addressInfo[1], addressInfo[2], addressInfo[3],
					                addressInfo[4][0], addressInfo[4][1]]
					updatedData.extend(locationInfo)

				# similarly, we have to treat gas prices as a special case as well, as the individual components are
				# associated with the "fuelTypes" tag
				elif tag == FUEL_PRICES_TAG:
					if sellsGas:
						updatedData.extend(parse_fuel_info(rawData))
					else:
						updatedData.extend(["'0'", "NULL", "NULL", "NULL"])

				# Turn python type True into a '1' or '0' for entry in PostgreSQL. This step is probably not needed,
				# but it is standard with my preferred SQL syntax style.
				elif tag in BOOLEAN_TAGS:
					if tag == "isActive":
						updatedData.append("'1'")
					else:
						if rawData:
							updatedData.append("'1'")
						else:
							updatedData.append("'0'")

				# all other values can be taken as is, surrounded by single quotes
				else:
					if type(rawData) is str:
						escapeApost = rawData.replace("'", "''")
						updatedData.append(quotify(escapeApost))
					else:
						updatedData.append(quotify(rawData))

			# update the database record
			for index, field in enumerate(HEADER):
				sql += "{0}={1},\n".format(field, updatedData[index])
			sql = sql[:-2] + "\nWHERE {0}='{1}';".format(locationIDField, storeNumber)

			try:
				cursor.execute(sql)
			except psycopg2.IntegrityError:
				connection.rollback()  # rollback bad transaction
			except psycopg2.ProgrammingError:
				print
				print "Error with SQL, make sure your fields are named as they were on initial download:"
				print ", ".format(HEADER)
				sys.exit(1)

		bar.next()

	# set all the inactive Wawas' isActive fields to false
	sql = "UPDATE {0} SET isActive='f' WHERE {1} IN ({2})".format(tableName, locationIDField, ", ".join(fails))
	cursor.execute(sql)

	# commit changes and release any possible locks
	connection.commit()
	connection.close()
	del cursor, connection

	print "\nFollowing store numbers no longer in Wawa's " \
	      "system and have been set to inactive: {0}.".format(", ".join(fails))
	print "Finished."
