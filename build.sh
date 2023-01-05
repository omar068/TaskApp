#!/usr/bin/env bash
# exit on error
set -o errexit

poetry install
sudo apt install libpq-dev python3-dev

pip install wheel
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate