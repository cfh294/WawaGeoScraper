"""
cmd_line
utility functions for the command line aspect of this project
"""

import argparse


def validate_csv_path(in_path):
    """
    Validates that the user input a .csv file path
    :param in_path: the input path     (str)
    :return:        the path, if valid (str)
    """
    if in_path.split(".")[-1:][0] != "csv":
        raise argparse.ArgumentTypeError("Must be a csv file.")
    else:
        return in_path


def get_csv_arg_parser():
    """
    :return: An argparse object for this project
    """
    ap = argparse.ArgumentParser(prog="Wawa Locations to CSV")
    ap.add_argument("location", help="A file path for the output .csv file.", type=validate_csv_path)
    ap.add_argument("--limit", "-l", help="Limit of results", type=int, default=None)
    return ap
