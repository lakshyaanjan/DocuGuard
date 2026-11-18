import argparse

DEFAULT_PORT = 9000

parser = argparse.ArgumentParser(
    description="My Application"
)

parser.add_argument(
    "--old-name",
    help="Launch the application using the old name option."
)

args = parser.parse_args()