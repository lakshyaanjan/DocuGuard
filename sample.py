import argparse

DEFAULT_PORT = 9000

parser = argparse.ArgumentParser(
    description="My Application"
)

parser.add_argument(
    "--new-name",
    help="Launch the application using the new name option."
)

args = parser.parse_args()
