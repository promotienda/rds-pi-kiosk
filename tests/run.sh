#!/bin/sh
# Unit tests: kiosk.txt parser and the setup page. Python 3 standard library only.
set -e
cd "$(dirname "$0")"
python3 -m unittest -v test_kioskconf test_setupd
