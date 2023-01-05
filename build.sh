#!/usr/bin/env bash
# exit on error
set -o errexit

#poetry install
sudo apt install python3-dev
sudo apt install libpq-dev
sudo apt install python3-pip
sudo apt install python3-venv
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install wheel
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate