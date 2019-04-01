#!/usr/bin/env python3
"""
Command line tool for pulling new Wawa location data into a .csv file
Usage:

chmod +x wawa_to_csv.py
./wawa_to_csv.py path/to/output/file.csv

For additional help:
./wawa_to_csv.py -h
"""
import csv
from utils.scraping import get_wawa_data
from utils.cmd_line import get_csv_arg_parser


if __name__ == "__main__":
    arg_parser = get_csv_arg_parser()
    args = arg_parser.parse_args()
    rows = get_wawa_data(args.limit)

    if len(rows) > 0:
        column_names = list(rows[0].keys())
        with open(args.location, "w") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=column_names)
            writer.writeheader()
            writer.writerows(rows)

