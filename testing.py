import os
import json
if __name__ == "__main__":
	projectRoot = os.path.dirname(os.path.abspath(__file__))
	jsonFile = os.path.join(projectRoot, "grid.json")

	points = []
	with open(jsonFile) as f:
		features = json.load(f)["features"]
		for feature in features:

			coords = feature["geometry"]["coordinates"]
			point = (float(coords[0]), float(coords[1]))
			points.append(point)
	return points

