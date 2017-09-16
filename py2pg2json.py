#!/usr/bin/python
"""
py2pg2json.py

A quick and dirty script that creates a grid for the Wawa scraper that is clipped to only be within the tested
states' boundaries. The output is a json file with each point in the grid.

This is free, open source software.
License: https://www.gnu.org/licenses/gpl-3.0.en.html

Code by Connor Hornibrook (c) 2017
"""

import psycopg2
import os
from scraperUtils import create_grid, FL_BOX, MID_ATL_BOX

if __name__ == "__main__":

	# out outer shell for the geojson
	geoJsonFmt = """{{"type": "FeatureCollection",
	"features": [{0}
]}}"""

	# grab the project root and connect to the database
	projectRoot = os.path.dirname(os.path.abspath(__file__))
	cnxn = psycopg2.connect(os.environ["NJGEODATA_CNXN"])
	cursor = cnxn.cursor()

	# create the un-clipped grid
	points = create_grid(FL_BOX)
	points.extend(create_grid(MID_ATL_BOX))

	# create a temporary table for the un-clipped grid in postgresql
	sql = """
	DROP TABLE IF EXISTS public.wawaGrid;
	CREATE TABLE public.wawaGrid
	(
		LONGITUDE   DOUBLE PRECISION,
		LATITUDE    DOUBLE PRECISION,
		GEOM        GEOMETRY
	);
	"""
	cursor.execute(sql)

	# insert the points from the un-clipped grid into the table
	for point in points:
		x, y = point[0], point[1]
		sql = """
		INSERT INTO public.wawaGrid (LONGITUDE, LATITUDE, GEOM)
		VALUES ({0}, {1}, (SELECT ST_SetSRID(ST_Point({0}, {1}), 4326)));
		""".format(x, y)

		try:
			cursor.execute(sql)
		except psycopg2.IntegrityError:
			cnxn.rollback()

	# using a spatial table I have of the United States, clip the grid to only be in the states that have Wawas.
	sql = """
	DROP TABLE IF EXISTS tmp;
	DROP TABLE IF EXISTS clipped_points;
	SELECT ST_UNION(geom) INTO tmp FROM public.us_state_shapes_4326
	WHERE stusps IN ('PA', 'NJ', 'MD', 'VA', 'DE', 'FL');

	SELECT LONGITUDE, LATITUDE INTO clipped_points FROM public.wawagrid WHERE ST_INTERSECTS(geom, (SELECT * FROM tmp));
	DROP TABLE tmp;
	DROP TABLE public.wawagrid;
	"""
	cursor.execute(sql)

	# grab these clipped points and store them in a python list object
	sql = "SELECT * FROM clipped_points;"
	cursor.execute(sql)
	clippedPoints = cursor.fetchall()
	cursor.execute("DROP TABLE clipped_points;")

	# a json format for each point
	featureFmt = """
	{{"type": "Feature",
	  "geometry": {{
	    "type": "Point",
	    "coordinates": [{0}, {1}]
	  }},
	  "properties": {{}}
	}},"""
	features = ""

	# create each json point, add to the overall feature string
	for point in clippedPoints:
		x, y = float(point[0]), float(point[1])
		features += featureFmt.format(x, y)

	# strip the end comma
	features = features[:-1]

	# place features into the feature collection
	geojson = geoJsonFmt.format(features)

	# close the connection and release possible memory locks
	cnxn.commit()
	cnxn.close()
	del cursor, cnxn

	# write the json to file in local dir
	with open(os.path.join(projectRoot, "grid.json"), "w") as jsonFile:
		jsonFile.write(geojson)
